from fastapi import APIRouter, Depends, HTTPException, status, Form
from xhs_utils.xhs_tools import get_xs
from schemas import XhsCollectParams

router = APIRouter()

@router.post("/get_xs")
def calculate_xs(a1: str, params: XhsCollectParams):
    api = "/api/sns/web/v2/note/collect/page"
    xs = get_xs(api, a1, data=params.model_dump())
    return {"xs": xs}
    
