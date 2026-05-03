from typing import Optional

from gemini_files import upload_inline_file, transcribe_uploaded_file
from message import download_telegram_file, send_document_bytes, send_message

MAX_AUDIO_BYTES = 50 * 1024 * 1024
async def transcribe_audio_bytes(audio_bytes: bytes, mime_type: str, display_name: str = "audio", chat_id: Optional[int] = None) -> tuple[Optional[str], Optional[str]]:
    file_uri, used_mime, key = await upload_inline_file(audio_bytes, mime_type, display_name)
    if not file_uri:
        return None, key or "Failed to upload file"

    model = "gemini-2.5-flash"
    return await transcribe_uploaded_file(file_uri, used_mime or mime_type, key, model=model)


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
