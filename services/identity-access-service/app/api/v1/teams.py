import uuid

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import Caller, pagination, require_permission
from app.application import team_service
from app.core.database import get_db
from app.schemas.common import ERROR_RESPONSES, Page
from app.schemas.teams import MemberAdd, MemberOut, TeamCreate, TeamOut, TeamPatch

router = APIRouter(prefix="/teams", tags=["Teams"], responses=ERROR_RESPONSES)


@router.post("", response_model=TeamOut, status_code=201, summary="Create a team (also defines its TEAM scope)")
def create_team(body: TeamCreate, c: Caller = Depends(require_permission("iam.team.manage")), db: Session = Depends(get_db)):
    return team_service.create_team(db, c.ctx, body)


@router.get("", response_model=Page[TeamOut], summary="List teams")
def list_teams(status: str | None = Query(None, pattern="^(ACTIVE|INACTIVE)$"), q: str | None = Query(None, max_length=64),
               page: tuple[int, int] = Depends(pagination), c: Caller = Depends(require_permission("iam.team.read")),
               db: Session = Depends(get_db)):
    items, total = team_service.list_teams(db, status=status, q=q, limit=page[0], offset=page[1])
    return Page(items=items, total=total, limit=page[0], offset=page[1])


@router.get("/{team_id}", response_model=TeamOut, summary="Get a team")
def get_team(team_id: uuid.UUID, c: Caller = Depends(require_permission("iam.team.read")), db: Session = Depends(get_db)):
    return team_service.get_team(db, team_id)


@router.patch("/{team_id}", response_model=TeamOut, summary="Update a team")
def patch_team(team_id: uuid.UUID, body: TeamPatch, c: Caller = Depends(require_permission("iam.team.manage")),
               db: Session = Depends(get_db)):
    return team_service.update_team(db, c.ctx, team_id, body)


@router.get("/{team_id}/members", response_model=list[MemberOut], summary="List active team members")
def list_members(team_id: uuid.UUID, c: Caller = Depends(require_permission("iam.team.read")), db: Session = Depends(get_db)):
    return team_service.list_members(db, team_id)


@router.post("/{team_id}/members", response_model=MemberOut, status_code=201, summary="Add a team member")
def add_member(team_id: uuid.UUID, body: MemberAdd, c: Caller = Depends(require_permission("iam.team.manage")),
               db: Session = Depends(get_db)):
    return team_service.add_member(db, c.ctx, team_id, body.user_id, body.member_role)


@router.delete("/{team_id}/members/{user_id}", status_code=204, summary="Remove a team member")
def remove_member(team_id: uuid.UUID, user_id: uuid.UUID, c: Caller = Depends(require_permission("iam.team.manage")),
                  db: Session = Depends(get_db)):
    team_service.remove_member(db, c.ctx, team_id, user_id)
    return Response(status_code=204)
