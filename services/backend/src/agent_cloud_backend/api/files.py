import mimetypes
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse

from agent_cloud_backend.config import Settings, get_settings
from agent_cloud_backend.files.deps import get_file_store
from agent_cloud_backend.files.errors import FileConflict, FileTooLarge, PathEscape
from agent_cloud_backend.files.store import FileStore
from agent_cloud_backend.schemas.file import FileEntryRead, MkdirRequest, MoveRequest

router = APIRouter(prefix="/files", tags=["files"])

_CHUNK = 1024 * 1024


def _http_from(exc: Exception) -> HTTPException:
    if isinstance(exc, PathEscape):
        return HTTPException(status.HTTP_400_BAD_REQUEST, "invalid path")
    if isinstance(exc, FileConflict):
        return HTTPException(status.HTTP_409_CONFLICT, "already exists")
    if isinstance(exc, FileTooLarge):
        return HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "file too large")
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    if isinstance(exc, (NotADirectoryError, IsADirectoryError)):
        return HTTPException(status.HTTP_400_BAD_REQUEST, "wrong file type")
    raise exc  # 未知错误 → 冒泡成 500


@router.get("", response_model=list[FileEntryRead])
def list_files(
    user_id: uuid.UUID,
    path: str = "",
    store: FileStore = Depends(get_file_store),
):
    try:
        return store.list_dir(str(user_id), path)
    except Exception as exc:
        raise _http_from(exc) from exc


@router.get("/raw")
def raw(
    user_id: uuid.UUID,
    path: str,
    attachment: bool = False,
    store: FileStore = Depends(get_file_store),
):
    uid = str(user_id)
    try:
        entry = store.stat(uid, path)
    except Exception as exc:
        raise _http_from(exc) from exc
    if entry.is_dir:
        name = (entry.name or "workspace") + ".zip"
        return StreamingResponse(
            store.zip_dir(uid, path),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )
    fh = store.open_read(uid, path)
    media = mimetypes.guess_type(entry.name)[0] or "application/octet-stream"
    disp = "attachment" if attachment else "inline"

    def _stream():
        try:
            yield from iter(lambda: fh.read(_CHUNK), b"")
        finally:
            fh.close()

    return StreamingResponse(
        _stream(),
        media_type=media,
        headers={"Content-Disposition": f'{disp}; filename="{entry.name}"'},
    )


@router.post("/upload", response_model=list[FileEntryRead], status_code=status.HTTP_201_CREATED)
def upload(
    user_id: uuid.UUID,
    path: str = "",
    files: list[UploadFile] = File(...),
    store: FileStore = Depends(get_file_store),
    settings: Settings = Depends(get_settings),
):
    out = []
    for uf in files:
        name = Path(uf.filename or "upload").name  # 只取 basename,消毒
        dest = f"{path}/{name}" if path else name
        try:
            out.append(store.write(str(user_id), dest, uf.file, settings.file_upload_max_bytes))
        except Exception as exc:
            raise _http_from(exc) from exc
    return out


@router.post("/mkdir", response_model=FileEntryRead)
def mkdir(body: MkdirRequest, store: FileStore = Depends(get_file_store)):
    try:
        return store.mkdir(body.user_id, body.path)
    except Exception as exc:
        raise _http_from(exc) from exc


@router.post("/move", response_model=FileEntryRead)
def move(body: MoveRequest, store: FileStore = Depends(get_file_store)):
    try:
        return store.move(body.user_id, body.src, body.dst)
    except Exception as exc:
        raise _http_from(exc) from exc


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete(
    user_id: uuid.UUID,
    path: str,
    store: FileStore = Depends(get_file_store),
):
    try:
        store.delete(str(user_id), path)
    except Exception as exc:
        raise _http_from(exc) from exc
