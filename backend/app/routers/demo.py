from fastapi import APIRouter, HTTPException
from app.config import settings
from app.security import create_demo_token
router = APIRouter()
@router.post("/demo/session", status_code=201)
def demo_session():
    if not settings.demo_mode:
        raise HTTPException(404, "Not found")
    token, expires_in = create_demo_token()
    return {"access_token": token, "expires_in": expires_in}
