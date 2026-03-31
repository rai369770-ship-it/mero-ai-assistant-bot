import base64
from typing import Optional
from database import save_message, get_file_data, get_user_voice
from message import send_message, download_telegram_file, send_chat_action, send_voice_bytes
from upload import upload_to_gemini_files
from api import call_gemini_raw, handle_gemini
from system import get_system_text
from tts import generate_tts


async def handle_voice(cid: int, voice: dict, name: str) -> None:
    if voice.get("duration", 0) > 300:
        await send_message(cid, "⚠️ Voice messages up to 5 minutes only.")
        return
    await send_chat_action(cid, "typing")
    await send_message(cid, "🎙️ Processing voice...")
    voice_data = await download_telegram_file(voice["file_id"])
    if not voice_data:
        await send_message(cid, "❌ Failed to download voice message.")
        return
    mime_type = voice.get("mime_type", "audio/ogg")
    uploaded_voice = await upload_to_gemini_files(voice_data, mime_type, "voice_message.ogg")
    if uploaded_voice:
        transcription = await call_gemini_raw(
            [
                {"text": "Transcribe the following voice in the original language. Don't write anything else except transcription."},
                {"fileData": {"mimeType": uploaded_voice["mime_type"], "fileUri": uploaded_voice["uri"]}},
            ],
            "You are a transcription engine. Output only the transcription.",
        )
    else:
        encoded_voice = base64.b64encode(voice_data).decode("utf-8")
        transcription = await call_gemini_raw(
            [
                {"text": "Transcribe the following voice in the original language. Don't write anything else except transcription."},
                {"inlineData": {"mimeType": mime_type, "data": encoded_voice}},
            ],
            "You are a transcription engine. Output only the transcription.",
        )
    if not transcription:
        await send_message(cid, "❌ Failed to transcribe voice message.")
        return
    save_message(cid, "user", f"[Voice] {transcription}")
    current_parts: list = [{"text": transcription}]
    file_data = get_file_data(cid)
    has_file = False
    if file_data and file_data.get("uri"):
        current_parts.append({"fileData": {"mimeType": file_data["mime_type"], "fileUri": file_data["uri"]}})
        has_file = True
    elif file_data and file_data.get("base64"):
        current_parts.append({"inlineData": {"mimeType": file_data["mime_type"], "data": file_data["base64"]}})
        has_file = True
    ai_response = await handle_gemini(cid, current_parts, get_system_text(name, cid), use_tools=not has_file)
    if ai_response and ai_response not in ("No response received from AI.", "Failed to parse AI response."):
        user_voice = get_user_voice(cid)
        tts_text = ai_response[:300]
        await send_chat_action(cid, "record_voice")
        audio_bytes = await generate_tts(tts_text, user_voice)
        if audio_bytes:
            await send_voice_bytes(cid, audio_bytes, "🎙️ Voice response")