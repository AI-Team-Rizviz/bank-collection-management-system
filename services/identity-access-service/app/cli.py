"""Operator CLI (needs DB access, i.e. a trusted operator; not exposed over HTTP).

  python -m app.cli bootstrap-admin --subject <oidc-sub> --username <name> --email <addr> --display-name "<name>"

Creates the very first System Administrators without any shared secret: the account is bound to the OIDC
subject, so the person still has to authenticate through the bank's identity provider. Run it once per
administrator (maker-checker needs at least two). Every run is audited.
"""
from __future__ import annotations

import typer
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import get_sessionmaker
from app.domain.models import Role, User, UserRole
from app.infrastructure import audit_repository as audit
from app.infrastructure.audit_repository import ActorContext

cli = typer.Typer(no_args_is_help=True, add_completion=False)
ADMIN_ROLE = "SYSTEM_ADMINISTRATOR"


@cli.callback()
def _root() -> None:
    """IAM operator commands."""


@cli.command("bootstrap-admin")
def bootstrap_admin(subject: str = typer.Option(..., help="OIDC `sub` of the administrator"),
                    username: str = typer.Option(...), email: str = typer.Option(...),
                    display_name: str = typer.Option(...)) -> None:
    if subject in get_settings().service_subjects:
        typer.secho("Subject is reserved for a service identity.", fg="red", err=True)
        raise typer.Exit(2)
    with get_sessionmaker()() as db:
        role = db.scalar(select(Role).where(Role.code == ADMIN_ROLE))
        if role is None:
            typer.secho("Role catalog missing: run `python -m seed.cli identity seed` first.", fg="red", err=True)
            raise typer.Exit(1)
        if db.scalar(select(User.id).where((User.external_identity_id == subject) | (User.username == username)
                                           | (User.email == email.lower()))):
            typer.secho("A user with that subject, username or email already exists.", fg="red", err=True)
            raise typer.Exit(1)
        user = User(external_identity_id=subject, username=username, display_name=display_name, email=email.lower())
        db.add(user)
        db.flush()
        db.add(UserRole(user_id=user.id, role_id=role.id))
        audit.record(db, ActorContext.system("cli.bootstrap-admin"), "user.bootstrap_admin", target_type="user",
                     target_id=user.id, details={"username": username, "role": ADMIN_ROLE})
        db.commit()
    typer.echo(f"Created system administrator '{username}'.")


if __name__ == "__main__":
    cli()
