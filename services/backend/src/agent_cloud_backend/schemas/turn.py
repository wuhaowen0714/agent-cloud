from pydantic import BaseModel

from agent_cloud_backend.schemas.message import MessageRead


class TurnRequest(BaseModel):
    content: str
    images: list[str] = []  # 本回合上传的图片工作区相对路径(多模态;spec: image-understanding)
    client: str = "web"  # 客户端平台(web/mobile);mobile 时往 system prompt 注入手机环境段


class TurnUsage(BaseModel):
    input_tokens: int
    output_tokens: int


class TurnResponse(BaseModel):
    messages: list[MessageRead]  # 本回合新增的 assistant/tool 消息
    stop_reason: str
    usage: TurnUsage
