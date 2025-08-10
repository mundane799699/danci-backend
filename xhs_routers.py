from fastapi import APIRouter, HTTPException

from schemas import XhsCalculateXsRequest, XhsCalculateXsResponse
from xhs_utils.xhs_tools import get_xs

router = APIRouter()


@router.post("/get_xs", response_model=XhsCalculateXsResponse)
def calculate_xs(request: XhsCalculateXsRequest) -> XhsCalculateXsResponse:
    """
    计算小红书接口的xs签名值

    Args:
        request: 包含api路径、a1值和可选参数的请求体

    Returns:
        包含xs签名值的响应字典

    Raises:
        HTTPException: 当签名计算失败时
    """
    try:
        # 直接使用params参数，因为它已经是dict类型
        params_data = request.params
        xs = get_xs(request.api, request.a1, params_data)

        return XhsCalculateXsResponse(xs=xs)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"计算xs签名失败: {str(e)}")
