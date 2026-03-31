import base64
from typing import Optional
from upload import upload_to_gemini_files
from api import call_gemini_raw


async def transcribe_audio_bytes(cid: int, audio_bytes: bytes, mime_type: str, display_name: str = "voice_message.ogg") -> Optional[str]:
    uploaded = await upload_to_gemini_files(audio_bytes, mime_type, display_name)
    prompt = "Transcribe the following voice in the original language. Output only the transcription."
    if uploaded:
        return await call_gemini_raw(
            [
                {"text": prompt},
                {"fileData": {"mimeType": uploaded["mime_type"], "fileUri": uploaded["uri"]}},
            ],
            "You are a transcription engine. Output only the transcription.",
            cid=cid,
        )
    encoded_voice = base64.b64encode(audio_bytes).decode("utf-8")
    return await call_gemini_raw(
        [
            {"text": prompt},
            {"inlineData": {"mimeType": mime_type, "data": encoded_voice}},
        ],
        "You are a transcription engine. Output only the transcription.",
        cid=cid,
    )


def extract_text_from_txt(file_bytes: bytes) -> str:
    for enc in ("utf-8", "utf-8-sig", "utf-16", "latin-1"):
        try:
            return file_bytes.decode(enc).strip()
        except Exception:
            continue
    return file_bytes.decode("utf-8", errors="ignore").strip()
