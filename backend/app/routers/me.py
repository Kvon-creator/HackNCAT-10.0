from fastapi import APIRouter, Depends
from app.security import current_user
from app.schemas.opportunity import Preferences
from app import demo_store
from app.config import settings
from app.services.demo_feed import rerank_feed

router = APIRouter()

@router.get("/me")
def get_me(user=Depends(current_user)):
    profile = demo_store.profiles.get(user["sub"], {})
    return {"id": user["sub"], "display_name": "Demo Student",
            "preferences": profile, "mode": "demo"}

@router.put("/me/preferences")
def update_preferences(payload: Preferences, user=Depends(current_user)):
    user_id = user["sub"]
    preferences = payload.model_dump()
    with demo_store.seed_lock:
        demo_store.profiles[user_id] = preferences
        if settings.demo_mode:
            indices = [i for i, item in enumerate(demo_store.feed_items) if item.get("user_id") == user_id]
            if indices:
                old_items = [demo_store.feed_items[i] for i in indices]
                reranked = rerank_feed(old_items, preferences)
                for i in reversed(indices):
                    del demo_store.feed_items[i]
                demo_store.feed_items.extend(reranked)
    return preferences
