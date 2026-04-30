import json
from typing import Optional

import httpx

from api import extract_ai_text, get_model_for_user
from api_keys import fetch_api_keys, get_keys
from message import download_telegram_file, send_document_bytes, send_message

MAX_AUDIO_BYTES = 50 * 1024 * 1024
TRANSCRIBE_PROMPT = "Transcribe the uploaded audio in the original language accurately without any timestamps. Punctuate and enhance grammar quality of the transcribed text. Only return the final transcribed text. Don't write anything else except transcription."


async def _ordered_keys() -> list[str]:
    ok = await fetch_api_keys()
    if not ok:
        return []
    return [k for k in get_keys() if k]


async def _upload_file_bytes(audio_bytes: bytes, mime_type: str, display_name: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    keys = await _ordered_keys()
    if not keys:
        return None, None, "No API keys available"

    async with httpx.AsyncClient(timeout=180.0) as client:
        for key in keys:
            start_url = "https://generativelanguage.googleapis.com/upload/v1beta/files"
            headers = {
                "x-goog-api-key": key,
                "X-Goog-Upload-Protocol": "resumable",
                "X-Goog-Upload-Command": "start",
                "X-Goog-Upload-Header-Content-Length": str(len(audio_bytes)),
                "X-Goog-Upload-Header-Content-Type": mime_type,
                "Content-Type": "application/json",
            }
            body = {"file": {"display_name": display_name[:80] or "audio_upload"}}
            try:
                start_resp = await client.post(start_url, headers=headers, content=json.dumps(body))
            except Exception:
                continue
            if start_resp.status_code >= 400:
                continue
            upload_url = start_resp.headers.get("x-goog-upload-url")
            if not upload_url:
                continue

            upload_headers = {
                "Content-Length": str(len(audio_bytes)),
                "X-Goog-Upload-Offset": "0",
                "X-Goog-Upload-Command": "upload, finalize",
            }
            try:
                upload_resp = await client.post(upload_url, headers=upload_headers, content=audio_bytes)
            except Exception:
                continue
            if upload_resp.status_code >= 400:
                continue

            data = upload_resp.json()
            file_obj = data.get("file", {})
            file_uri = file_obj.get("uri")
            used_mime = file_obj.get("mimeType") or mime_type
            if file_uri:
                return file_uri, used_mime, key

    return None, None, "Failed to upload audio with available API keys"


async def transcribe_audio_bytes(audio_bytes: bytes, mime_type: str, display_name: str = "audio", chat_id: Optional[int] = None) -> tuple[Optional[str], Optional[str]]:
    file_uri, used_mime, key = await _upload_file_bytes(audio_bytes, mime_type, display_name)
    if not file_uri:
        return None, key or "Failed to upload file"

    # Use appropriate model based on user type
    model = get_model_for_user(chat_id) if chat_id else "gemini-2.5-flash"

    body = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"file_data": {"mime_type": used_mime or mime_type, "file_uri": file_uri}},
                    {"text": TRANSCRIBE_PROMPT},
                ],
            }
        ],
        "generationConfig": {"maxOutputTokens": 65636, "temperature": 2.0},
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(url, headers={"Content-Type": "application/json"}, content=json.dumps(body))
    if resp.status_code != 200:
        return None, f"Transcription request failed ({resp.status_code})"

    text, _ = extract_ai_text(resp.text)
    clean = (text or "").strip()
    if not clean or clean in ("No response received from AI.", "Failed to parse AI response."):
        return None, "Empty transcription result"
    return clean, None


async def transcribe_from_telegram_message(cid: int, message: dict) -> bool:
    voice = message.get("voice")
    audio = message.get("audio")
    document = message.get("document")

    if voice:
        file_id = voice.get("file_id")
        file_size = int(voice.get("file_size", 0) or 0)
        mime_type = voice.get("mime_type") or "audio/ogg"
        display_name = "voice.ogg"
    elif audio:
        file_id = audio.get("file_id")
        file_size = int(audio.get("file_size", 0) or 0)
        mime_type = audio.get("mime_type") or "audio/mpeg"
        display_name = audio.get("file_name") or "audio"
    elif document:
        file_id = document.get("file_id")
        file_size = int(document.get("file_size", 0) or 0)
        mime_type = document.get("mime_type") or "application/octet-stream"
        display_name = document.get("file_name") or "audio"
    else:
        await send_message(cid, "❌ Please upload a valid voice or audio file.")
        return False

    if file_size > MAX_AUDIO_BYTES:
        await send_message(cid, "⚠️ Audio must be under 50 MB.")
        return False

    await send_message(cid, "🎙️ Transcribing your audio...")
    audio_bytes = await download_telegram_file(file_id)
    if not audio_bytes:
        await send_message(cid, "❌ Failed to download your audio.")
        return False

    transcription, error = await transcribe_audio_bytes(audio_bytes, mime_type, display_name, chat_id=cid)
    if error or not transcription:
        await send_message(cid, f"❌ Transcription failed. {error or ''}".strip())
        return False

    if len(transcription) > 4000:
        await send_document_bytes(
            cid,
            transcription.encode("utf-8"),
            "transcription.txt",
            "✅ Transcription is attached as text file.",
            mime_type="text/plain",
        )
    else:
        await send_message(cid, transcription)
    return True
