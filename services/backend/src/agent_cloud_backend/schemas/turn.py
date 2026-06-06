from pydantic import BaseModel

from agent_cloud_backend.schemas.message import MessageRead


class TurnRequest(BaseModel):
    content: str


class TurnUsage(BaseModel):
    input_tokens: int
    output_tokens: int


class TurnResponse(BaseModel):
    messages: list[MessageRead]   # 本回合新增的 assistant/tool 消息
    stop_reason: str
    usage: TurnUsage
