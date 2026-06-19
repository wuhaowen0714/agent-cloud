"""平台默认 provider(sophnet)的模型清单 —— session 选 sophnet 时的 model 候选。
BYOK provider 的模型走用户 credential.models。"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from agent_cloud_backend.api.deps import get_current_user
from agent_cloud_backend.config import Settings, get_settings
from agent_cloud_backend.models.user import User

router = APIRouter(prefix="/platform", tags=["platform"])


class PlatformModels(BaseModel):
    models: list[str]
    default: str
    vision_models: list[str]  # models 中支持图片输入的子集(前端路由用;spec: image-understanding)


@router.get("/models", response_model=PlatformModels)
async def get_platform_models(
    _user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> PlatformModels:
    return PlatformModels(
        models=settings.platform_models,
        default=settings.resolve_default_model(),
        vision_models=settings.vision_models,
    )
