from pydantic import BaseModel, ConfigDict


class FileEntryRead(BaseModel):
    # 从 FileStore 的 FileEntry dataclass 读属性序列化
    model_config = ConfigDict(from_attributes=True)

    name: str
    path: str
    is_dir: bool
    size: int
    mtime: float


class MkdirRequest(BaseModel):
    user_id: str
    path: str


class MoveRequest(BaseModel):
    user_id: str
    src: str
    dst: str
