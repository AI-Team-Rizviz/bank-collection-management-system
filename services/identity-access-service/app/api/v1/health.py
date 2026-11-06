from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("/live", summary="Liveness probe")
def live():
    return {"status": "ok"}


@router.get("/ready", summary="Readiness probe (database reachable and migrated)")
def ready(response: Response, db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1 FROM alembic_version_iam LIMIT 1")).first()
        return {"status": "ready"}
    except Exception:
        response.status_code = 503
        return {"status": "unavailable"}
