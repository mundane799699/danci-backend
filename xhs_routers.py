from fastapi import APIRouter

from schemas import XhsCalculateXsRequest
from xhs_utils.xhs_tools import get_xs

router = APIRouter()


@router.post("/get_xs")
def calculate_xs(request: XhsCalculateXsRequest):
    xs = get_xs(request.api, request.a1, data=request.params.model_dump())
    return {"xs": xs}
