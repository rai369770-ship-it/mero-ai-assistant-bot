import base64
from typing import Optional
from database import save_message, save_file_data, set_state, ensure_user
from message import send_message, send_chat_action, download_telegram_file, get_telegram_file_info
from upload import upload_to_gemini_files, detect_mime_type, get_display_name
from api import handle_gemini
from system import get_system_text
from settings import photo_keyboard, file_prompt_keyboard
from markdown_parse import escape_html


def encode_inline(file_bytes: bytes, mime: str, file_name: str, display_name: Optional[str] = None) -> dict:
    return {
        "uri": "",
        "mime_type": mime,
        "name": file_name,
        "display_name": display_name or file_name,
        "base64": base64.b64encode(file_bytes).decode("utf-8"),
    }


def set_pending_file_prompt(cid: int, file_name: str) -> str:
    set_state(cid, f"awaiting_file_prompt:{file_name}")
    return f"✅ File uploaded: <b>{escape_html(file_name)}</b>\n\nType your prompt for this file."


async def handle_photo(cid: int, message: dict, name: str) -> None:
    ensure_user(cid, name)
    best_photo = message["photo"][-1]
    caption = message.get("caption", "").strip()
    await send_chat_action(cid, "typing")
    await send_message(cid, "🖼️ Uploading image...")
    file_info = await get_telegram_file_info(best_photo["file_id"])
    if not file_info:
        await send_message(cid, "❌ Failed to get image info.")
        return
    file_bytes = await download_telegram_file(best_photo["file_id"])
    if not file_bytes:
        await send_message(cid, "❌ Failed to download image.")
        return
    file_path = file_info.get("file_path", "photo.jpg")
    display = get_display_name(file_path, "photo.jpg")
    mime = detect_mime_type(file_path, "image/jpeg")
    uploaded = await upload_to_gemini_files(file_bytes, mime, display)
    stored = uploaded or encode_inline(file_bytes, mime, display, display)
    save_file_data(cid, stored)
    if caption:
        save_message(cid, "user", f"[Image: {display}] {caption}")
        parts = [{"text": caption}]
        if uploaded:
            parts.append({"fileData": {"mimeType": stored["mime_type"], "fileUri": stored["uri"]}})
        else:
            parts.append({"inlineData": {"mimeType": stored["mime_type"], "data": stored["base64"]}})
        await handle_gemini(cid, parts, get_system_text(name, cid), use_tools=False)
        return
    await send_message(
        cid,
        f"✅ Image uploaded: <b>{escape_html(display)}</b>\n\nType your prompt or tap Describe.",
        parse_mode="HTML",
        reply_markup=photo_keyboard(),
    )


async def handle_document(cid: int, message: dict, name: str) -> None:
    ensure_user(cid, name)
    doc = message["document"]
    file_name = doc.get("file_name", "document")
    provided_mime = doc.get("mime_type", "")
    caption = message.get("caption", "").strip()
    file_size = doc.get("file_size", 0)
    if file_size > 20 * 1024 * 1024:
        await send_message(cid, "⚠️ File too large. Maximum 20MB supported.")
        return
    await send_chat_action(cid, "typing")
    await send_message(cid, f"📄 Uploading <b>{escape_html(file_name)}</b>...", parse_mode="HTML")
    file_bytes = await download_telegram_file(doc["file_id"])
    if not file_bytes:
        await send_message(cid, "❌ Failed to download file.")
        return
    file_info = await get_telegram_file_info(doc["file_id"])
    file_path = file_info.get("file_path", file_name) if file_info else file_name
    mime = detect_mime_type(file_path, provided_mime)
    uploaded = await upload_to_gemini_files(file_bytes, mime, file_name)
    stored = uploaded or encode_inline(file_bytes, mime, file_name)
    save_file_data(cid, stored)
    if caption:
        save_message(cid, "user", f"[File: {file_name}] {caption}")
        parts = [{"text": caption}]
        if uploaded:
            parts.append({"fileData": {"mimeType": stored["mime_type"], "fileUri": stored["uri"]}})
        else:
            parts.append({"inlineData": {"mimeType": stored["mime_type"], "data": stored["base64"]}})
        await handle_gemini(cid, parts, get_system_text(name, cid), use_tools=False)
        return
    await send_message(cid, set_pending_file_prompt(cid, file_name), parse_mode="HTML", reply_markup=file_prompt_keyboard())


async def handle_audio(cid: int, message: dict, name: str) -> None:
    ensure_user(cid, name)
    audio = message["audio"]
    file_name = audio.get("file_name", "audio.mp3")
    provided_mime = audio.get("mime_type", "audio/mpeg")
    caption = message.get("caption", "").strip()
    file_size = audio.get("file_size", 0)
    if file_size > 20 * 1024 * 1024:
        await send_message(cid, "⚠️ Audio too large. Maximum 20MB.")
        return
    await send_chat_action(cid, "typing")
    await send_message(cid, f"🎵 Uploading <b>{escape_html(file_name)}</b>...", parse_mode="HTML")
    file_bytes = await download_telegram_file(audio["file_id"])
    if not file_bytes:
        await send_message(cid, "❌ Failed to download audio.")
        return
    mime = detect_mime_type(file_name, provided_mime)
    uploaded = await upload_to_gemini_files(file_bytes, mime, file_name)
    stored = uploaded or encode_inline(file_bytes, mime, file_name)
    save_file_data(cid, stored)
    if caption:
        save_message(cid, "user", f"[Audio: {file_name}] {caption}")
        parts = [{"text": caption}]
        if uploaded:
            parts.append({"fileData": {"mimeType": stored["mime_type"], "fileUri": stored["uri"]}})
        else:
            parts.append({"inlineData": {"mimeType": stored["mime_type"], "data": stored["base64"]}})
        await handle_gemini(cid, parts, get_system_text(name, cid), use_tools=False)
        return
    set_state(cid, f"awaiting_file_prompt:{file_name}")
    await send_message(
        cid,
        f"✅ Audio uploaded: <b>{escape_html(file_name)}</b>\n\nType your prompt for this audio.",
        parse_mode="HTML",
        reply_markup=file_prompt_keyboard(),
    )


async def handle_video(cid: int, message: dict, name: str) -> None:
    ensure_user(cid, name)
    video = message.get("video") or message.get("video_note", {})
    file_name = video.get("file_name", "video.mp4")
    provided_mime = video.get("mime_type", "video/mp4")
    caption = message.get("caption", "").strip()
    file_size = video.get("file_size", 0)
    if file_size > 20 * 1024 * 1024:
        await send_message(cid, "⚠️ Video too large. Maximum 20MB.")
        return
    await send_chat_action(cid, "typing")
    await send_message(cid, f"🎬 Uploading <b>{escape_html(file_name)}</b>...", parse_mode="HTML")
    file_bytes = await download_telegram_file(video["file_id"])
    if not file_bytes:
        await send_message(cid, "❌ Failed to download video.")
        return
    mime = detect_mime_type(file_name, provided_mime)
    uploaded = await upload_to_gemini_files(file_bytes, mime, file_name)
    stored = uploaded or encode_inline(file_bytes, mime, file_name)
    save_file_data(cid, stored)
    if caption:
        save_message(cid, "user", f"[Video: {file_name}] {caption}")
        parts = [{"text": caption}]
        if uploaded:
            parts.append({"fileData": {"mimeType": stored["mime_type"], "fileUri": stored["uri"]}})
        else:
            parts.append({"inlineData": {"mimeType": stored["mime_type"], "data": stored["base64"]}})
        await handle_gemini(cid, parts, get_system_text(name, cid), use_tools=False)
        return
    set_state(cid, f"awaiting_file_prompt:{file_name}")
    await send_message(
        cid,
        f"✅ Video uploaded: <b>{escape_html(file_name)}</b>\n\nType your prompt for this video.",
        parse_mode="HTML",
        reply_markup=file_prompt_keyboard(),
    )


async def handle_animation(cid: int, message: dict, name: str) -> None:
    ensure_user(cid, name)
    anim = message["animation"]
    file_name = anim.get("file_name", "animation.gif")
    provided_mime = anim.get("mime_type", "video/mp4")
    caption = message.get("caption", "").strip()
    await send_chat_action(cid, "typing")
    await send_message(cid, f"🎞️ Uploading <b>{escape_html(file_name)}</b>...", parse_mode="HTML")
    file_bytes = await download_telegram_file(anim["file_id"])
    if not file_bytes:
        await send_message(cid, "❌ Failed to download animation.")
        return
    mime = detect_mime_type(file_name, provided_mime)
    uploaded = await upload_to_gemini_files(file_bytes, mime, file_name)
    stored = uploaded or encode_inline(file_bytes, mime, file_name)
    save_file_data(cid, stored)
    if caption:
        save_message(cid, "user", f"[Animation: {file_name}] {caption}")
        parts = [{"text": caption}]
        if uploaded:
            parts.append({"fileData": {"mimeType": stored["mime_type"], "fileUri": stored["uri"]}})
        else:
            parts.append({"inlineData": {"mimeType": stored["mime_type"], "data": stored["base64"]}})
        await handle_gemini(cid, parts, get_system_text(name, cid), use_tools=False)
        return
    set_state(cid, f"awaiting_file_prompt:{file_name}")
    await send_message(cid, f"✅ Animation uploaded: <b>{escape_html(file_name)}</b>\n\nType your prompt.", parse_mode="HTML", reply_markup=file_prompt_keyboard())


async def handle_sticker(cid: int, message: dict, name: str) -> None:
    ensure_user(cid, name)
    sticker = message["sticker"]
    if sticker.get("is_animated") or sticker.get("is_video"):
        await send_message(cid, "⚠️ Animated/video stickers are not supported. Send a static sticker.")
        return
    await send_chat_action(cid, "typing")
    file_bytes = await download_telegram_file(sticker["file_id"])
    if not file_bytes:
        await send_message(cid, "❌ Failed to download sticker.")
        return
    uploaded = await upload_to_gemini_files(file_bytes, "image/webp", "sticker.webp")
    if uploaded:
        save_message(cid, "user", "[Sticker] Describe this sticker")
        parts: list = [
            {"text": "Describe this sticker and react to it naturally."},
            {"fileData": {"mimeType": uploaded["mime_type"], "fileUri": uploaded["uri"]}},
        ]
        await handle_gemini(cid, parts, get_system_text(name, cid), use_tools=False)
        return
    encoded = base64.b64encode(file_bytes).decode("utf-8")
    save_message(cid, "user", "[Sticker] Describe this sticker")
    await handle_gemini(
        cid,
        [{"text": "Describe this sticker and react to it naturally."}, {"inlineData": {"mimeType": "image/webp", "data": encoded}}],
        get_system_text(name, cid),
        use_tools=False,
    )
