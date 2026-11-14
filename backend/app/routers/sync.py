from fastapi import APIRouter, Depends

from app.errors import graph_api_error
from app.security import current_user
from app.services.graph_service import GraphServiceError
from app.services.sync_service import sync_user

router = APIRouter()


@router.post("/sync")
def sync_inbox(user=Depends(current_user)):
    try:
        return sync_user(user)
    except GraphServiceError as error:
        raise graph_api_error(error) from None
