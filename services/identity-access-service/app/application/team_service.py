from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application import scope_service
from app.application.common import get_or_404, insert_or_conflict, paginate, utcnow
from app.core.exceptions import Conflict, NotFound
from app.domain.models import Team, TeamMember, User
from app.infrastructure import audit_repository as audit
from app.infrastructure.audit_repository import ActorContext


def create_team(db: Session, ctx: ActorContext, data) -> Team:
    team = Team(code=data.code, name=data.name, description=data.description, branch_id=data.branch_id,
                region_id=data.region_id, created_by=ctx.user_id, updated_by=ctx.user_id)
    insert_or_conflict(db, team, "A team with this code already exists")
    scope_service.ensure_team_scope(db, ctx, team)
    audit.record(db, ctx, "team.create", target_type="team", target_id=team.id, details={"code": team.code})
    return team


def get_team(db: Session, team_id: uuid.UUID) -> Team:
    return get_or_404(db, Team, team_id, "Team")


def list_teams(db: Session, *, status: str | None, q: str | None, limit: int, offset: int):
    stmt = select(Team).order_by(Team.code)
    if status:
        stmt = stmt.where(Team.status == status)
    if q:
        stmt = stmt.where(Team.code.like(q.upper().replace("%", r"\%") + "%"))
    return paginate(db, stmt, limit, offset)


def update_team(db: Session, ctx: ActorContext, team_id: uuid.UUID, patch) -> Team:
    team = get_or_404(db, Team, team_id, "Team")
    changes = patch.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(team, k, v)
    team.updated_by = ctx.user_id
    db.flush()
    audit.record(db, ctx, "team.update", target_type="team", target_id=team.id, details={"fields": ",".join(changes)})
    return team


def list_members(db: Session, team_id: uuid.UUID) -> list[TeamMember]:
    get_or_404(db, Team, team_id, "Team")
    return list(db.scalars(select(TeamMember).where(TeamMember.team_id == team_id, TeamMember.status == "ACTIVE")))


def add_member(db: Session, ctx: ActorContext, team_id: uuid.UUID, user_id: uuid.UUID, member_role: str) -> TeamMember:
    team = get_or_404(db, Team, team_id, "Team")
    user = get_or_404(db, User, user_id, "User")
    if team.status != "ACTIVE" or user.status != "ACTIVE":
        raise Conflict("Team and user must be active")
    m = TeamMember(team_id=team_id, user_id=user_id, member_role=member_role, added_by=ctx.user_id)
    insert_or_conflict(db, m, "User is already a member of this team")
    audit.record(db, ctx, "team.member_add", target_type="team", target_id=team_id,
                 details={"user_id": user_id, "member_role": member_role})
    return m


def remove_member(db: Session, ctx: ActorContext, team_id: uuid.UUID, user_id: uuid.UUID) -> None:
    get_or_404(db, Team, team_id, "Team")
    m = db.scalar(select(TeamMember).where(TeamMember.team_id == team_id, TeamMember.user_id == user_id,
                                           TeamMember.status == "ACTIVE"))
    if m is None:
        raise NotFound("Team membership not found")
    m.status, m.left_at = "REMOVED", utcnow()
    db.flush()
    audit.record(db, ctx, "team.member_remove", target_type="team", target_id=team_id, details={"user_id": user_id})
