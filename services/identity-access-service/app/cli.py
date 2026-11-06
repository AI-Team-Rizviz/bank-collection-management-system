"""Operator CLI (needs DB access, i.e. a trusted operator; not exposed over HTTP).

  python -m app.cli bootstrap-admin --username <name> --email <addr> --display-name "<name>"   (prompts for a password)
  python -m app.cli set-password --username <name>                                           (prompts for a password)
  python -m app.cli issue-service-token --subject <svc-name> [--days 90]                     (subject must be in SERVICE_SUBJECTS)

Creates the very first System Administrators and resets passwords. The password is read from an interactive prompt
(never a command-line argument, so it stays out of shell history). Run bootstrap-admin once per administrator
(maker-checker needs at least two). Every run is audited.
"""
from __future__ import annotations

import typer
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import get_sessionmaker
from app.core.passwords import check_strength, hash_password
from app.domain.models import Role, User, UserRole
from app.infrastructure import audit_repository as audit
from app.infrastructure.audit_repository import ActorContext

cli = typer.Typer(no_args_is_help=True, add_completion=False)
ADMIN_ROLE = "SYSTEM_ADMINISTRATOR"


@cli.callback()
def _root() -> None:
    """IAM operator commands."""


def _password() -> str:
    pw = typer.prompt("Password", hide_input=True, confirmation_prompt=True)
    try:
        check_strength(pw)
    except ValueError as exc:
        typer.secho(str(exc), fg="red", err=True)
        raise typer.Exit(2) from exc
    return pw


@cli.command("bootstrap-admin")
def bootstrap_admin(username: str = typer.Option(...), email: str = typer.Option(...),
                    display_name: str = typer.Option(...)) -> None:
    password = _password()
    with get_sessionmaker()() as db:
        role = db.scalar(select(Role).where(Role.code == ADMIN_ROLE))
        if role is None:
            typer.secho("Role catalog missing: run `python -m seed.cli identity seed` first.", fg="red", err=True)
            raise typer.Exit(1)
        if db.scalar(select(User.id).where((User.username == username) | (User.email == email.lower()))):
            typer.secho("A user with that username or email already exists.", fg="red", err=True)
            raise typer.Exit(1)
        user = User(external_identity_id=f"local-{username}", username=username, display_name=display_name,
                    email=email.lower(), password_hash=hash_password(password))
        db.add(user)
        db.flush()
        db.add(UserRole(user_id=user.id, role_id=role.id))
        audit.record(db, ActorContext.system("cli.bootstrap-admin"), "user.bootstrap_admin", target_type="user",
                     target_id=user.id, details={"username": username, "role": ADMIN_ROLE})
        db.commit()
    typer.echo(f"Created system administrator '{username}'.")


@cli.command("set-password")
def set_password(username: str = typer.Option(...)) -> None:
    password = _password()
    with get_sessionmaker()() as db:
        user = db.scalar(select(User).where(User.username == username))
        if user is None:
            typer.secho("No such user.", fg="red", err=True)
            raise typer.Exit(1)
        user.password_hash = hash_password(password)
        audit.record(db, ActorContext.system("cli.set-password"), "user.password_set", target_type="user", target_id=user.id)
        db.commit()
    typer.echo(f"Password updated for '{username}'.")


@cli.command("issue-service-token")
def issue_service_token(subject: str = typer.Option(..., help="Must be listed in SERVICE_SUBJECTS"),
                        days: int = typer.Option(90, min=1, max=365)) -> None:
    """Print a long-lived token for a trusted internal service (store it in that service's secret store)."""
    from app.infrastructure.tokens import TokenService

    settings = get_settings()
    if subject not in settings.service_subjects:
        typer.secho("Subject is not listed in SERVICE_SUBJECTS.", fg="red", err=True)
        raise typer.Exit(2)
    if not settings.jwt_secret_key:
        typer.secho("JWT_SECRET_KEY is not configured.", fg="red", err=True)
        raise typer.Exit(1)
    with get_sessionmaker()() as db:
        audit.record(db, ActorContext.system("cli.issue-service-token"), "service.token_issued",
                     target_type="service", details={"subject": subject, "days": days})
        db.commit()
    typer.echo(TokenService(settings.jwt_secret_key, days * 86400).issue(subject))


if __name__ == "__main__":
    cli()
