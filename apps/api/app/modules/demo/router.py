from fastapi import APIRouter

from app.core.config import get_settings
from app.modules.building.model import BuildingModel
from app.modules.demo.service import demo_building_model

router = APIRouter(prefix="/demo", tags=["demo"])


@router.get("/building-model")
async def get_demo_building_model() -> BuildingModel:
    """Public, read-only: the hand-authored Phase 1 demo house."""
    return demo_building_model(get_settings().data_dir)
