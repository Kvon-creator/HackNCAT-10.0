from fastapi import APIRouter, Depends
from app.security import current_user
from app.schemas.opportunity import Preferences

router = APIRouter()
# In-memory demo state only. Replace with user-scoped PostgreSQL repository before live use.
_profiles: dict[str, dict] = {}

@router.get("/me")
def get_me(user=Depends(current_user)):
    profile = _profiles.get(user["sub"], {})
    return {"id": user["sub"], "display_name": "Demo Student",
            "preferences": profile, "mode": "demo"}

@router.put("/me/preferences")
def update_preferences(payload: Preferences, user=Depends(current_user)):
    _profiles[user["sub"]] = payload.model_dump()
    return _profiles[user["sub"]]
