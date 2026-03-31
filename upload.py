import json
import asyncio
import httpx
from typing import Optional
from api_keys import fetch_api_keys, get_keys_turn_by_turn
from config import GEMINI_FILES_API, GEMINI_FILES_GET, SUPPORTED_MIME_TYPES, CODE_EXTENSIONS


async def upload_to_gemini_files(file_bytes: bytes, mime_type: str, display_name: str) -> Optional[dict]:
    if not await fetch_api_keys():
        return None
    keys = get_keys_turn_by_turn()
    if not keys:
        return None
    metadata = json.dumps({"file": {"displayName": display_name}})
    boundary = "----GeminiBoundary7MA4YWxkTrZu0gW"
    body = (
        f"--{boundary}\r\n"
        f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{metadata}\r\n"
        f"--{boundary}\r\n"
        f"Content-Type: {mime_type}\r\n\r\n"
    ).encode("utf-8") + file_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")
    headers = {"Content-Type": f"multipart/related; boundary={boundary}"}
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            for key in keys:
                upload_url = f"{GEMINI_FILES_API}?key={key}"
                resp = await client.post(upload_url, content=body, headers=headers)
                if resp.status_code != 200:
                    continue
                result = resp.json()
                file_info = result.get("file", {})
                file_uri = file_info.get("uri", "")
                file_name = file_info.get("name", "")
                state = file_info.get("state", "")
                if state == "PROCESSING":
                    for _ in range(30):
                        await asyncio.sleep(2)
                        check_resp = await client.get(f"{GEMINI_FILES_GET}/{file_name}?key={key}")
                        if check_resp.status_code != 200:
                            continue
                        check_data = check_resp.json()
                        if check_data.get("state") == "ACTIVE":
                            return {
                                "uri": check_data.get("uri", file_uri),
                                "mime_type": check_data.get("mimeType", mime_type),
                                "name": file_name,
                                "display_name": display_name,
                            }
                    continue
                return {
                    "uri": file_uri,
                    "mime_type": mime_type,
                    "name": file_name,
                    "display_name": display_name,
                }
    except Exception:
        pass
    return None


def detect_mime_type(file_path: str, provided_mime: Optional[str] = None) -> str:
    if provided_mime and provided_mime in SUPPORTED_MIME_TYPES:
        return provided_mime
    ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
    ext_to_mime = {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "doc": "application/msword",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xls": "application/vnd.ms-excel",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "ppt": "application/vnd.ms-powerpoint",
        "txt": "text/plain",
        "csv": "text/csv",
        "html": "text/html",
        "css": "text/css",
        "js": "application/javascript",
        "json": "application/json",
        "xml": "application/xml",
        "py": "text/x-python",
        "java": "text/x-java-source",
        "c": "text/x-c",
        "cpp": "text/x-c++",
        "cs": "text/x-csharp",
        "go": "text/x-go",
        "rs": "text/x-rust",
        "rb": "text/x-ruby",
        "php": "text/x-php",
        "swift": "text/x-swift",
        "kt": "text/x-kotlin",
        "scala": "text/x-scala",
        "sh": "text/x-shellscript",
        "sql": "text/x-sql",
        "yaml": "application/x-yaml",
        "yml": "application/x-yaml",
        "toml": "text/x-toml",
        "md": "text/markdown",
        "ts": "application/typescript",
        "tsx": "application/typescript",
        "jsx": "application/javascript",
        "lua": "text/x-lua",
        "pl": "text/x-perl",
        "r": "text/x-r",
        "dart": "text/x-dart",
        "mp3": "audio/mpeg",
        "m4a": "audio/mp4",
        "ogg": "audio/ogg",
        "wav": "audio/wav",
        "webm": "audio/webm",
        "flac": "audio/flac",
        "aac": "audio/aac",
        "mp4": "video/mp4",
        "mov": "video/quicktime",
        "avi": "video/x-msvideo",
        "mkv": "video/x-matroska",
        "3gp": "video/3gpp",
    }
    if ext in ext_to_mime:
        return ext_to_mime[ext]
    if ext in CODE_EXTENSIONS:
        return "text/plain"
    if provided_mime:
        return provided_mime
    return "application/octet-stream"


def get_display_name(file_path: str, file_name: Optional[str] = None) -> str:
    if file_name:
        return file_name
    if "." in file_path:
        return file_path.rsplit("/", 1)[-1]
    return "uploaded_file"