"""The sport catalogue, for the dashboard."""

from fastapi import APIRouter

from app.schemas.sport import SportRead
from app.services.sports import SPORTS

router = APIRouter(tags=["sports"])


@router.get("/sports", response_model=list[SportRead])
def list_sports() -> list[SportRead]:
    """Every sport the app knows, in display order.

    A stored sport missing from this list is one a file named that has no entry
    yet; the dashboard reads it by speed, in the "other" colour.
    """
    return [SportRead.model_validate(sport) for sport in SPORTS]
