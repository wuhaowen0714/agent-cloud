import mimetypes
from urllib.parse import quote

from agent_cloud_common import extract_text
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse

from agent_cloud_backend.api.deps import get_current_user
from agent_cloud_backend.config import Settings, get_settings
from agent_cloud_backend.files.deps import get_file_store
from agent_cloud_backend.files.errors import FileConflict, FileTooLarge, PathEscape
from agent_cloud_backend.files.store import FileStore
from agent_cloud_backend.models.user import User
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
    # FileExistsError:把文件当目录用(move/upload 到 file/inner)→ 4xx 而非 500(I1)
    if isinstance(exc, (FileExistsError, NotADirectoryError, IsADirectoryError)):
        return HTTPException(status.HTTP_400_BAD_REQUEST, "wrong file type")
    # 其余 OSError(如 ENAMETOOLONG:超长段/超深嵌套):围栏内的非法路径形态,
    # 是客户端输入问题 → 400 而非 500。必须放在上面更具体的 OSError 子类之后。
    if isinstance(exc, OSError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, "invalid path")
    raise exc  # 未知错误 → 冒泡成 500


def _sanitize_rel_upload_path(filename: str) -> str:
    """上传 filename → 围栏内相对路径。文件夹上传时 multipart filename 携带
    webkitRelativePath(如 proj/sub/a.txt),需保留目录结构;普通上传仍是 basename。
    消毒:`\\`→`/` 归一(Windows 风格)、拒 \\0、丢空段与 `.`、`..` 或空结果 → PathEscape
    (提前拦成 400;store._resolve 仍是最终围栏,双层防护)。"""
    raw = (filename or "").replace("\\", "/")
    if "\0" in raw:
        raise PathEscape("null byte in filename")
    parts = [p for p in raw.split("/") if p not in ("", ".")]
    if not parts:
        raise PathEscape("empty filename")
    if any(p == ".." for p in parts):
        raise PathEscape(f"parent traversal not allowed: {filename!r}")
    return "/".join(parts)


def _cd_filename(name: str) -> str:
    # 文件名可能含 " 或控制字符(沙箱可创建),会破坏 Content-Disposition 引号串(M1)
    return name.replace('"', "").replace("\r", "").replace("\n", "")


def _content_disposition(disp: str, name: str) -> str:
    """构造 Content-Disposition:HTTP 头只能 latin-1,非 ASCII 文件名(中文等)塞进
    filename="…" 会让 Starlette 直接 UnicodeEncodeError → 500(预览/下载双挂)。
    按 RFC 6266:filename= 放 ASCII 兜底(老客户端),filename*=UTF-8'' 放百分号
    编码的真名(现代浏览器优先取它,下载落地仍是原文件名)。"""
    safe = _cd_filename(name)
    ascii_fallback = safe.encode("ascii", "ignore").decode() or "download"
    return f"{disp}; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(safe, safe='')}"


@router.get("", response_model=list[FileEntryRead])
def list_files(
    path: str = "",
    store: FileStore = Depends(get_file_store),
    user: User = Depends(get_current_user),
):
    try:
        return store.list_dir(str(user.id), path)
    except Exception as exc:
        raise _http_from(exc) from exc


@router.get("/index", response_model=list[str])
def index_files(
    store: FileStore = Depends(get_file_store),
    user: User = Depends(get_current_user),
):
    """工作区全部文件的相对路径(composer @ 文件引用的索引)。无路径入参,无越狱面。"""
    try:
        return store.walk(str(user.id))
    except Exception as exc:
        raise _http_from(exc) from exc


@router.get("/raw")
def raw(
    path: str,
    attachment: bool = False,
    store: FileStore = Depends(get_file_store),
    user: User = Depends(get_current_user),
):
    uid = str(user.id)
    try:
        entry = store.stat(uid, path)
    except Exception as exc:
        raise _http_from(exc) from exc
    if entry.is_dir:
        return StreamingResponse(
            store.zip_dir(uid, path),
            media_type="application/zip",
            headers={
                "Content-Disposition": _content_disposition(
                    "attachment", (entry.name or "workspace") + ".zip"
                )
            },
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
        headers={"Content-Disposition": _content_disposition(disp, entry.name)},
    )


@router.get("/extract")
def extract(
    path: str,
    store: FileStore = Depends(get_file_store),
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    """把文档(pdf/docx/pptx/xlsx)抽成文本供前端预览,复用 read_file 工具的 extract_text。"""
    uid = str(user.id)
    try:
        entry = store.stat(uid, path)  # 404 / 越狱防护
        if entry.is_dir:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "is a directory")
        text = extract_text(store.abspath(uid, path))
    except HTTPException:
        raise
    except RuntimeError as exc:
        # extract_text 的友好错误(损坏/超大/扫描件)→ 当预览文本展示,不冒泡成 500
        text = f"⚠️ {exc}"
    except Exception as exc:
        raise _http_from(exc) from exc
    return {"text": text}


@router.post("/upload", response_model=list[FileEntryRead], status_code=status.HTTP_201_CREATED)
def upload(
    path: str = "",
    files: list[UploadFile] = File(...),
    store: FileStore = Depends(get_file_store),
    settings: Settings = Depends(get_settings),
    user: User = Depends(get_current_user),
):
    out = []
    for uf in files:
        try:
            name = _sanitize_rel_upload_path(uf.filename or "upload")
            dest = f"{path}/{name}" if path else name
            out.append(store.write(str(user.id), dest, uf.file, settings.file_upload_max_bytes))
        except Exception as exc:
            raise _http_from(exc) from exc
    return out


@router.post("/mkdir", response_model=FileEntryRead)
def mkdir(
    body: MkdirRequest,
    store: FileStore = Depends(get_file_store),
    user: User = Depends(get_current_user),
):
    try:
        return store.mkdir(str(user.id), body.path)
    except Exception as exc:
        raise _http_from(exc) from exc


@router.post("/move", response_model=FileEntryRead)
def move(
    body: MoveRequest,
    store: FileStore = Depends(get_file_store),
    user: User = Depends(get_current_user),
):
    try:
        return store.move(str(user.id), body.src, body.dst)
    except Exception as exc:
        raise _http_from(exc) from exc


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete(
    path: str,
    store: FileStore = Depends(get_file_store),
    user: User = Depends(get_current_user),
):
    try:
        store.delete(str(user.id), path)
    except Exception as exc:
        raise _http_from(exc) from exc
