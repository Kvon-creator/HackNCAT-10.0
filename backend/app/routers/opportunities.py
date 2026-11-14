from fastapi import APIRouter, Depends, HTTPException, Query
from uuid import UUID
from app.security import current_user

router = APIRouter()
# Replace with repository queries scoped by authenticated user ID.
_demo_items: list[dict] = []

@router.get("/opportunities")
def list_opportunities(q: str | None = None, category: str | None = None,
                       priority: str | None = None, saved: bool | None = None,
                       limit: int = Query(20, ge=1, le=50), offset: int = Query(0, ge=0),
                       user=Depends(current_user)):
    rows = [x for x in _demo_items if x.get("user_id") == user["sub"]]
    if q:
        rows = [x for x in rows if q.lower() in (x["title"] + " " + x["summary"]).lower()]
    if category:
        rows = [x for x in rows if x["category"] == category]
    if priority:
        rows = [x for x in rows if x["priority"] == priority]
    if saved is not None:
        rows = [x for x in rows if x.get("saved", False) == saved]
    return {"items": rows[offset:offset+limit], "total": len(rows)}

@router.get("/opportunities/{opportunity_id}")
def get_opportunity(opportunity_id: UUID, user=Depends(current_user)):
    for item in _demo_items:
        if item["id"] == str(opportunity_id) and item.get("user_id") == user["sub"]:
            return item
    raise HTTPException(404, "Opportunity not found")

@router.post("/opportunities/{opportunity_id}/save", status_code=204)
def save_opportunity(opportunity_id: UUID, user=Depends(current_user)):
    for item in _demo_items:
        if item["id"] == str(opportunity_id) and item.get("user_id") == user["sub"]:
            item["saved"] = True
            return
    raise HTTPException(404, "Opportunity not found")

@router.delete("/opportunities/{opportunity_id}/save", status_code=204)
def unsave_opportunity(opportunity_id: UUID, user=Depends(current_user)):
    for item in _demo_items:
        if item["id"] == str(opportunity_id) and item.get("user_id") == user["sub"]:
            item["saved"] = False
            return
    raise HTTPException(404, "Opportunity not found")
