from fastapi import APIRouter, Depends, HTTPException, Query
from uuid import UUID
from app.config import settings
from app import demo_store
from app.security import current_user
from app.services.demo_feed import build_demo_feed, to_public

router = APIRouter()

def _user_items_unlocked(user_id: str) -> list[dict]:
    rows = [x for x in demo_store.feed_items if x.get("user_id") == user_id]
    if not rows and settings.demo_mode:
        demo_store.feed_items.extend(
            build_demo_feed(user_id, demo_store.profiles.get(user_id))
        )
        rows = [x for x in demo_store.feed_items if x.get("user_id") == user_id]
    return rows

def _user_items(user_id: str) -> list[dict]:
    """Return a user's rows, seeding them once in demo mode."""
    with demo_store.seed_lock:
        return _user_items_unlocked(user_id)

@router.get("/opportunities")
def list_opportunities(q: str | None = None, category: str | None = None,
                       priority: str | None = None, saved: bool | None = None,
                       limit: int = Query(20, ge=1, le=50), offset: int = Query(0, ge=0),
                       user=Depends(current_user)):
    rows = _user_items(user["sub"])
    if q:
        rows = [x for x in rows if q.lower() in (x["title"] + " " + x["summary"]).lower()]
    if category:
        rows = [x for x in rows if x["category"] == category]
    if priority:
        rows = [x for x in rows if x["priority"] == priority]
    if saved is not None:
        rows = [x for x in rows if x.get("saved", False) == saved]
    return {"items": [to_public(x) for x in rows[offset:offset+limit]], "total": len(rows)}

@router.get("/opportunities/{opportunity_id}")
def get_opportunity(opportunity_id: UUID, user=Depends(current_user)):
    for item in _user_items(user["sub"]):
        if item["id"] == str(opportunity_id) and item.get("user_id") == user["sub"]:
            return to_public(item)
    raise HTTPException(404, "Opportunity not found")

@router.post("/opportunities/{opportunity_id}/save", status_code=204)
def save_opportunity(opportunity_id: UUID, user=Depends(current_user)):
    with demo_store.seed_lock:
        for item in _user_items_unlocked(user["sub"]):
            if item["id"] == str(opportunity_id) and item.get("user_id") == user["sub"]:
                item["saved"] = True
                return
    raise HTTPException(404, "Opportunity not found")

@router.delete("/opportunities/{opportunity_id}/save", status_code=204)
def unsave_opportunity(opportunity_id: UUID, user=Depends(current_user)):
    with demo_store.seed_lock:
        for item in _user_items_unlocked(user["sub"]):
            if item["id"] == str(opportunity_id) and item.get("user_id") == user["sub"]:
                item["saved"] = False
                return
    raise HTTPException(404, "Opportunity not found")
