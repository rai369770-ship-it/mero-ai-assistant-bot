import json
from typing import Optional

import httpx

from api import extract_ai_text
from api_keys import fetch_api_keys, get_keys

TRANSCRIBE_PROMPT = (
    "Transcribe the uploaded audio exactly in its original language. "
    "Do not summarize. Do not translate. Return only the transcript text."
)


async def ordered_keys() -> list[str]:
    ok = await fetch_api_keys()
    if not ok:
        return []
    return [k for k in get_keys() if k]


async def upload_inline_file(audio_bytes: bytes, mime_type: str, display_name: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    keys = await ordered_keys()
    if not keys:
        return None, None, "No API keys available"

    async with httpx.AsyncClient(timeout=180.0) as client:
        for key in keys:
            try:
                start_resp = await client.post(
                    "https://generativelanguage.googleapis.com/upload/v1beta/files",
                    headers={
                        "x-goog-api-key": key,
                        "X-Goog-Upload-Protocol": "resumable",
                        "X-Goog-Upload-Command": "start",
                        "X-Goog-Upload-Header-Content-Length": str(len(audio_bytes)),
                        "X-Goog-Upload-Header-Content-Type": mime_type,
                        "Content-Type": "application/json",
                    },
                    json={"file": {"display_name": display_name[:80] or "audio_upload"}},
                )
                if start_resp.status_code >= 400:
                    continue
                upload_url = start_resp.headers.get("x-goog-upload-url")
                if not upload_url:
                    continue
                upload_resp = await client.post(
                    upload_url,
                    headers={
                        "Content-Length": str(len(audio_bytes)),
                        "X-Goog-Upload-Offset": "0",
                        "X-Goog-Upload-Command": "upload, finalize",
                    },
                    content=audio_bytes,
                )
                if upload_resp.status_code >= 400:
                    continue
                data = upload_resp.json()
                file_obj = data.get("file", {})
                file_uri = file_obj.get("uri")
                used_mime = file_obj.get("mimeType") or mime_type
                if file_uri:
                    return file_uri, used_mime, key
            except Exception:
                continue
    return None, None, "Failed to upload audio with available API keys"


async def transcribe_uploaded_file(file_uri: str, mime_type: str, api_key: str, model: str = "gemini-2.5-flash") -> tuple[Optional[str], Optional[str]]:
    body = {
        "contents": [{"role": "user", "parts": [{"file_data": {"mime_type": mime_type, "file_uri": file_uri}}, {"text": TRANSCRIBE_PROMPT}]}],
        "generationConfig": {"maxOutputTokens": 65536, "temperature": 0.0},
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(url, headers={"Content-Type": "application/json"}, content=json.dumps(body))
    if resp.status_code != 200:
        return None, f"Transcription request failed ({resp.status_code})"
    text, _ = extract_ai_text(resp.text)
    clean = (text or "").strip()
    if not clean or clean in ("No response received from AI.", "Failed to parse AI response."):
        return None, "Empty transcription result"
    return clean, None
