from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from config import ADMINS, TEMPLATE_PROMPTS, SHARE_TEXT, MAX_HISTORY
from database import (
    save_user, user_exists, remove_all_user_data, get_all_users,
    ban_user, unban_user, is_banned, get_banned_users,
    save_message, get_all_history, clear_history,
    set_reply_state, get_reply_state, clear_reply_state,
    set_state, get_state, clear_state,
    save_file_data, get_file_data, clear_file_data,
    get_user_voice, set_user_voice, get_user_system, set_user_system,
    clear_user_system, get_user_temp, set_user_temp, get_user_model, set_user_model,
    ensure_user, is_admin, check_banned,
)
from message import (
    send_message, send_photo, send_voice_bytes,
    download_telegram_file, get_telegram_file_info,
    answer_callback, edit_message, delete_message,
    send_chat_action, send_document_bytes,
)
from settings import (
    btn, url_btn, ikb,
    start_keyboard, template_prompts_keyboard,
    user_settings_keyboard, admin_settings_keyboard,
    voice_keyboard, temp_keyboard, model_keyboard, photo_keyboard, file_prompt_keyboard,
    admin_reply_keyboard, admin_user_reply_keyboard, broadcast_reply_keyboard,
    share_keyboard,
)
from markdown_parse import escape_html
from api import handle_gemini
from system import get_system_text
from agent import agent_route, execute_normal_message
from image_generation import execute_image
from voice_message import handle_voice
from transcriber import transcribe_audio_bytes, extract_text_from_txt
from attachment import (
    handle_photo, handle_document, handle_audio,
    handle_video, handle_animation, handle_sticker,
)

import urllib.parse

app = FastAPI()


def get_user_name(message: dict) -> str:
    user = message.get("from", {})
    name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
    return name or user.get("username", "User")


async def send_banned_message(cid: int) -> None:
    await send_message(
        cid,
        "🚫 Sorry, you're banned by the admin. You can't use the bot anymore.\n\nYou can request the admin to unban you.",
        reply_markup=ikb([[btn("📩 Request Unban", "request_unban")]]),
    )


@app.get("/")
async def home():
    return {"status": "ok", "message": "Mero AI Assistant Bot is running!"}


@app.post("/webhook")
async def webhook(request: Request):
    try:
        data = await request.json()

        if "callback_query" in data:
            cb = data["callback_query"]
            cb_id = cb["id"]
            cb_data = cb.get("data", "")
            cid = cb["message"]["chat"]["id"]
            mid = cb["message"]["message_id"]
            name = get_user_name(cb)

            if check_banned(cid) and cb_data != "request_unban":
                await answer_callback(cb_id, "You are banned.")
                return JSONResponse({"ok": True})

            if cb_data == "noop":
                await answer_callback(cb_id, "Processing...")
                return JSONResponse({"ok": True})

            if cb_data == "share_bot":
                await answer_callback(cb_id)
                await send_message(
                    cid,
                    f"📤 <b>Share Mero AI with your friends!</b>\n\n{escape_html(SHARE_TEXT)}",
                    parse_mode="HTML",
                    reply_markup=share_keyboard(),
                )
                return JSONResponse({"ok": True})

            if cb_data == "open_settings":
                await answer_callback(cb_id)
                kb = admin_settings_keyboard() if is_admin(cid) else user_settings_keyboard()
                await send_message(cid, "⚙️ <b>Settings</b>", parse_mode="HTML", reply_markup=kb)
                return JSONResponse({"ok": True})

            if cb_data == "request_unban":
                await answer_callback(cb_id, "Request sent!")
                for admin_id in ADMINS:
                    await send_message(
                        admin_id,
                        f"📩 <b>Unban Request</b>\n\n👤 {escape_html(name)}\n🆔 <code>{cid}</code>",
                        parse_mode="HTML",
                        reply_markup=ikb([
                            [btn("✅ Unban", f"do_unban:{cid}"), btn("❌ Reject", f"reject_unban:{cid}")],
                        ]),
                    )
                await send_message(cid, "📩 Your unban request has been sent to the admin.")
                return JSONResponse({"ok": True})

            if cb_data.startswith("do_unban:"):
                if not is_admin(cid):
                    await answer_callback(cb_id, "Unauthorized")
                    return JSONResponse({"ok": True})
                target = int(cb_data.split(":")[1])
                unban_user(target)
                await answer_callback(cb_id, "Unbanned!")
                await edit_message(cid, mid, f"✅ User <code>{target}</code> has been unbanned.", parse_mode="HTML")
                await send_message(target, "🎉 You have been unbanned! You can use the bot again. Send /start")
                return JSONResponse({"ok": True})

            if cb_data.startswith("reject_unban:"):
                if not is_admin(cid):
                    await answer_callback(cb_id, "Unauthorized")
                    return JSONResponse({"ok": True})
                target = int(cb_data.split(":")[1])
                await answer_callback(cb_id, "Rejected")
                await edit_message(cid, mid, f"❌ Unban request from <code>{target}</code> rejected.", parse_mode="HTML")
                await send_message(target, "❌ Your unban request was rejected by the admin.")
                return JSONResponse({"ok": True})

            if cb_data.startswith("tp:"):
                idx = int(cb_data.split(":")[1])
                if 0 <= idx < len(TEMPLATE_PROMPTS):
                    await answer_callback(cb_id)
                    ensure_user(cid, name)
                    await send_chat_action(cid, "typing")
                    await agent_route(cid, TEMPLATE_PROMPTS[idx], name)
                return JSONResponse({"ok": True})

            if cb_data == "describe_photo":
                await answer_callback(cb_id)
                fd = get_file_data(cid)
                if not fd:
                    await send_message(cid, "❌ No image found. Please send an image first.")
                    return JSONResponse({"ok": True})
                ensure_user(cid, name)
                await send_chat_action(cid, "typing")
                prompt = "Describe this image in detail."
                save_message(cid, "user", f"[Image] {prompt}")
                parts: list = [{"text": prompt}]
                if fd.get("uri"):
                    parts.append({"fileData": {"mimeType": fd["mime_type"], "fileUri": fd["uri"]}})
                elif fd.get("base64"):
                    parts.append({"inlineData": {"mimeType": fd["mime_type"], "data": fd["base64"]}})
                await handle_gemini(cid, parts, get_system_text(name, cid), use_tools=False)
                return JSONResponse({"ok": True})

            if cb_data == "cancel_attachment":
                await answer_callback(cb_id, "Cancelled")
                clear_file_data(cid)
                clear_state(cid)
                await edit_message(cid, mid, "✅ Attachment cancelled.")
                return JSONResponse({"ok": True})

            if cb_data == "history":
                await answer_callback(cb_id)
                history = get_all_history(cid)
                if not history:
                    await send_message(cid, "📜 No conversation history found.")
                else:
                    text_parts = [f"📜 <b>History ({len(history)} messages):</b>\n"]
                    for msg in history[-20:]:
                        label = "👤 You" if msg["role"] == "user" else "🤖 Mero AI"
                        t = msg.get("text", "")[:500]
                        text_parts.append(f"<b>{label}:</b>\n{escape_html(t)}\n")
                    await send_message(cid, "\n".join(text_parts), parse_mode="HTML")
                return JSONResponse({"ok": True})

            if cb_data == "export_chat":
                await answer_callback(cb_id)
                history = get_all_history(cid)
                if not history:
                    await send_message(cid, "📜 No conversation history to export.")
                    return JSONResponse({"ok": True})
                export_lines = []
                for msg in history:
                    role = "You" if msg["role"] == "user" else "Mero AI"
                    export_lines.append(f"[{role}]\n{msg.get('text', '')}\n")
                export_text = "\n---\n".join(export_lines)
                file_bytes = export_text.encode("utf-8")
                await send_document_bytes(cid, file_bytes, "chat_history.txt", "📜 Your chat history export")
                return JSONResponse({"ok": True})

            if cb_data == "clear":
                await answer_callback(cb_id)
                await send_message(cid, "⚠️ Clear chat history?", reply_markup=ikb([
                    [btn("✅ Yes", "clear_yes"), btn("❌ No", "clear_no")],
                ]))
                return JSONResponse({"ok": True})

            if cb_data == "clear_yes":
                await answer_callback(cb_id, "Cleared!")
                clear_history(cid)
                await edit_message(cid, mid, "🗑️ Conversation cleared.")
                return JSONResponse({"ok": True})

            if cb_data == "clear_no":
                await answer_callback(cb_id, "Cancelled")
                await edit_message(cid, mid, "✅ Clear cancelled.")
                return JSONResponse({"ok": True})

            if cb_data == "cls":
                await answer_callback(cb_id, "Attachment cleared!")
                clear_file_data(cid)
                await send_message(cid, "🧹 Stored attachment cleared.")
                return JSONResponse({"ok": True})

            if cb_data == "feedback_prompt":
                await answer_callback(cb_id)
                set_reply_state(cid, -1)
                await send_message(cid, "💬 Type your feedback or send voice:", reply_markup=ikb([[btn("❌ Cancel", "cancel_reply")]]))
                return JSONResponse({"ok": True})

            if cb_data == "cancel_reply":
                await answer_callback(cb_id, "Cancelled")
                clear_reply_state(cid)
                clear_state(cid)
                await edit_message(cid, mid, "✅ Cancelled.")
                return JSONResponse({"ok": True})

            if cb_data == "close_settings":
                await answer_callback(cb_id)
                await edit_message(cid, mid, "✅ Settings closed.")
                return JSONResponse({"ok": True})

            if cb_data == "back_settings":
                await answer_callback(cb_id)
                kb = admin_settings_keyboard() if is_admin(cid) else user_settings_keyboard()
                await edit_message(cid, mid, "⚙️ <b>Settings</b>", parse_mode="HTML", reply_markup=kb)
                return JSONResponse({"ok": True})

            if cb_data == "set_system":
                await answer_callback(cb_id)
                current = get_user_system(cid)
                info = f"Current: <i>{escape_html(current[:200])}</i>" if current else "No custom instructions set."
                set_state(cid, "awaiting_system_instructions")
                await send_message(
                    cid,
                    f"🧠 <b>System Instructions</b>\n\n{info}\n\nType text, send a voice message, or send a .txt file. You can also send /clear_system to remove:",
                    parse_mode="HTML",
                    reply_markup=ikb([
                        [btn("🗑️ Clear Instructions", "clear_system")],
                        [btn("🔙 Back", "back_settings")],
                    ]),
                )
                return JSONResponse({"ok": True})

            if cb_data == "clear_system":
                await answer_callback(cb_id, "Cleared!")
                clear_user_system(cid)
                clear_state(cid)
                await edit_message(cid, mid, "🗑️ System instructions cleared.", parse_mode="HTML")
                return JSONResponse({"ok": True})

            if cb_data == "set_voice":
                await answer_callback(cb_id)
                current_voice = get_user_voice(cid)
                await edit_message(
                    cid, mid,
                    f"🎙️ <b>TTS Voice Selection</b>\n\nCurrent: <code>{current_voice}</code>\n\nSelect a voice:",
                    parse_mode="HTML",
                    reply_markup=voice_keyboard(),
                )
                return JSONResponse({"ok": True})

            if cb_data.startswith("voice:"):
                voice_id = cb_data.split(":", 1)[1]
                set_user_voice(cid, voice_id)
                await answer_callback(cb_id, f"Voice set: {voice_id}")
                await edit_message(cid, mid, f"✅ Voice changed to <code>{voice_id}</code>", parse_mode="HTML", reply_markup=ikb([[btn("🔙 Back", "back_settings")]]))
                return JSONResponse({"ok": True})

            if cb_data == "set_model":
                await answer_callback(cb_id)
                current_model = get_user_model(cid)
                model_name = "Mero lite" if current_model == "gemini-2.5-flash-lite" else "Mero pro"
                await edit_message(
                    cid,
                    mid,
                    f"🧩 <b>AI Model</b>\n\nCurrent: <b>{model_name}</b>\n\nSelect model:",
                    parse_mode="HTML",
                    reply_markup=model_keyboard(current_model),
                )
                return JSONResponse({"ok": True})

            if cb_data.startswith("model:"):
                selected = cb_data.split(":", 1)[1]
                model_value = "gemini-2.5-flash-lite" if selected == "lite" else "gemini-2.5-flash"
                set_user_model(cid, model_value)
                await answer_callback(cb_id, "Model updated")
                model_name = "Mero lite" if model_value == "gemini-2.5-flash-lite" else "Mero pro"
                await edit_message(
                    cid,
                    mid,
                    f"✅ Model set to <b>{model_name}</b>",
                    parse_mode="HTML",
                    reply_markup=model_keyboard(model_value),
                )
                return JSONResponse({"ok": True})

            if cb_data == "set_temp":
                await answer_callback(cb_id)
                current_temp = get_user_temp(cid)
                await edit_message(
                    cid, mid,
                    f"🌡️ <b>Temperature Setting</b>\n\nCurrent: <code>{current_temp}</code>\n\nHigher = more creative, Lower = more precise:",
                    parse_mode="HTML",
                    reply_markup=temp_keyboard(),
                )
                return JSONResponse({"ok": True})

            if cb_data.startswith("temp:"):
                temp_val = float(cb_data.split(":")[1])
                set_user_temp(cid, temp_val)
                await answer_callback(cb_id, f"Temperature: {temp_val}")
                await edit_message(cid, mid, f"✅ Temperature set to <code>{temp_val}</code>", parse_mode="HTML", reply_markup=ikb([[btn("🔙 Back", "back_settings")]]))
                return JSONResponse({"ok": True})

            if cb_data.startswith("reply_admin:"):
                await answer_callback(cb_id)
                set_reply_state(cid, ADMINS[0])
                await send_message(cid, "✍️ Type your reply or send voice to admin:", reply_markup=ikb([[btn("❌ Cancel", "cancel_reply")]]))
                return JSONResponse({"ok": True})

            if cb_data.startswith("reply_user:"):
                target = int(cb_data.split(":")[1])
                await answer_callback(cb_id)
                set_reply_state(cid, target)
                await send_message(cid, f"✍️ Type reply or send voice to <code>{target}</code>:", parse_mode="HTML", reply_markup=ikb([[btn("❌ Cancel", "cancel_reply")]]))
                return JSONResponse({"ok": True})

            if cb_data.startswith("regen_img:"):
                prompt = cb_data.split(":", 1)[1]
                await answer_callback(cb_id, "Regenerating...")
                ensure_user(cid, name)
                await execute_image(cid, prompt, name)
                return JSONResponse({"ok": True})

            if cb_data == "admin_total":
                if not is_admin(cid):
                    await answer_callback(cb_id, "Unauthorized")
                    return JSONResponse({"ok": True})
                await answer_callback(cb_id)
                users = get_all_users()
                if not users:
                    await send_message(cid, "No users registered.", reply_markup=ikb([[btn("🔙 Back", "back_settings")]]))
                    return JSONResponse({"ok": True})
                rows = []
                text = f"📊 <b>Total Users: {len(users)}</b>\n\n"
                for uid_str, uname in users.items():
                    label = (uname or "User").strip() or "User"
                    text += f"🆔 <code>{uid_str}</code> — {escape_html(label)}\n"
                    if int(uid_str) not in ADMINS:
                        rows.append([
                            btn(f"💬 Message {label[:16]}", f"reply_user:{uid_str}"),
                            btn(f"🚫 Ban {label[:16]}", f"ban_confirm:{uid_str}"),
                        ])
                rows.append([btn("🔙 Back", "back_settings")])
                await send_message(cid, text, parse_mode="HTML", reply_markup=ikb(rows))
                return JSONResponse({"ok": True})

            if cb_data.startswith("ban_confirm:"):
                if not is_admin(cid):
                    await answer_callback(cb_id, "Unauthorized")
                    return JSONResponse({"ok": True})
                target_str = cb_data.split(":")[1]
                uname = get_all_users().get(target_str, "Unknown")
                await answer_callback(cb_id)
                await send_message(
                    cid,
                    f"⚠️ Ban <b>{escape_html(uname)}</b> (<code>{target_str}</code>)?",
                    parse_mode="HTML",
                    reply_markup=ikb([
                        [btn("✅ Yes, Ban", f"ban_yes:{target_str}"), btn("❌ Cancel", "back_settings")],
                    ]),
                )
                return JSONResponse({"ok": True})

            if cb_data.startswith("ban_yes:"):
                if not is_admin(cid):
                    await answer_callback(cb_id, "Unauthorized")
                    return JSONResponse({"ok": True})
                target = int(cb_data.split(":")[1])
                uname = get_all_users().get(str(target), "Unknown")
                ban_user(target, uname)
                await answer_callback(cb_id, "Banned!")
                await edit_message(cid, mid, f"🚫 <b>{escape_html(uname)}</b> (<code>{target}</code>) banned.", parse_mode="HTML")
                await send_message(target, "🚫 You have been banned from using this bot.")
                return JSONResponse({"ok": True})

            if cb_data == "admin_banned":
                if not is_admin(cid):
                    await answer_callback(cb_id, "Unauthorized")
                    return JSONResponse({"ok": True})
                await answer_callback(cb_id)
                banned = get_banned_users()
                if not banned:
                    await send_message(cid, "✅ No banned users.", reply_markup=ikb([[btn("🔙 Back", "back_settings")]]))
                    return JSONResponse({"ok": True})
                rows = []
                for uid_str, uname in banned.items():
                    rows.append([btn(f"✅ Unban {uname} ({uid_str})", f"do_unban:{uid_str}")])
                text = f"🚫 <b>Banned Users: {len(banned)}</b>\n\n"
                text += "".join(f"🆔 <code>{u}</code> — {escape_html(n)}\n" for u, n in banned.items())
                rows.append([btn("🔙 Back", "back_settings")])
                await send_message(cid, text, parse_mode="HTML", reply_markup=ikb(rows))
                return JSONResponse({"ok": True})

            if cb_data == "admin_broadcast":
                if not is_admin(cid):
                    await answer_callback(cb_id, "Unauthorized")
                    return JSONResponse({"ok": True})
                await answer_callback(cb_id)
                set_state(cid, "awaiting_broadcast")
                await send_message(cid, "📢 Send your broadcast as text or voice:", reply_markup=ikb([[btn("❌ Cancel", "cancel_reply")]]))
                return JSONResponse({"ok": True})

            return JSONResponse({"ok": True})

        if "message" not in data:
            return JSONResponse({"ok": True})

        message = data["message"]
        cid = message["chat"]["id"]
        name = get_user_name(message)

        if check_banned(cid):
            await send_banned_message(cid)
            return JSONResponse({"ok": True})

        st = get_state(cid)
        if st:
            if "text" in message:
                text = message["text"].strip()
                if text.startswith("/"):
                    clear_state(cid)
                else:
                    if st == "awaiting_system_instructions":
                        clear_state(cid)
                        set_user_system(cid, text)
                        await send_message(
                            cid,
                            f"✅ System instructions updated:\n\n<i>{escape_html(text[:500])}</i>",
                            parse_mode="HTML",
                            reply_markup=ikb([[btn("🔙 Back", "back_settings")]]),
                        )
                        return JSONResponse({"ok": True})
                    if st == "awaiting_broadcast":
                        clear_state(cid)
                        if not is_admin(cid):
                            return JSONResponse({"ok": True})
                        users = get_all_users()
                        success, fail = 0, 0
                        for uid in users:
                            try:
                                result = await send_message(
                                    int(uid),
                                    f"📢 <b>Broadcast:</b>\n\n{escape_html(text)}",
                                    parse_mode="HTML",
                                    reply_markup=broadcast_reply_keyboard(),
                                )
                                if result and result.get("ok"):
                                    success += 1
                                else:
                                    fail += 1
                            except Exception:
                                fail += 1
                        await send_message(cid, f"📢 Broadcast done.\n✅ Sent: {success}\n❌ Failed: {fail}")
                        return JSONResponse({"ok": True})
                    if st.startswith("awaiting_file_prompt:"):
                        clear_state(cid)
                        ensure_user(cid, name)
                        await send_chat_action(cid, "typing")
                        fd = get_file_data(cid)
                        if not fd:
                            await send_message(cid, "❌ File not found. Please upload again.")
                            return JSONResponse({"ok": True})
                        file_display = st.split(":", 1)[1] if ":" in st else "file"
                        save_message(cid, "user", f"[File: {file_display}] {text}")
                        parts: list = [{"text": text}]
                        if fd.get("uri"):
                            parts.append({"fileData": {"mimeType": fd["mime_type"], "fileUri": fd["uri"]}})
                        elif fd.get("base64"):
                            parts.append({"inlineData": {"mimeType": fd["mime_type"], "data": fd["base64"]}})
                        await handle_gemini(cid, parts, get_system_text(name, cid), use_tools=False)
                        return JSONResponse({"ok": True})
            if st == "awaiting_system_instructions" and message.get("voice"):
                clear_state(cid)
                voice_data = await download_telegram_file(message["voice"]["file_id"])
                if not voice_data:
                    await send_message(cid, "❌ Failed to download voice message.")
                    return JSONResponse({"ok": True})
                transcription = await transcribe_audio_bytes(cid, voice_data, message["voice"].get("mime_type", "audio/ogg"), "system_instruction.ogg")
                if not transcription:
                    await send_message(cid, "❌ Failed to transcribe voice message.")
                    return JSONResponse({"ok": True})
                set_user_system(cid, transcription)
                await send_message(
                    cid,
                    f"✅ System instructions updated from voice:\n\n<i>{escape_html(transcription[:500])}</i>",
                    parse_mode="HTML",
                    reply_markup=ikb([[btn("🔙 Back", "back_settings")]]),
                )
                return JSONResponse({"ok": True})
            if st == "awaiting_system_instructions" and message.get("document"):
                doc = message["document"]
                filename = (doc.get("file_name") or "").lower()
                mime = (doc.get("mime_type") or "").lower()
                if not (filename.endswith(".txt") or mime.startswith("text/plain")):
                    await send_message(cid, "❌ Send a .txt file for system instructions.")
                    return JSONResponse({"ok": True})
                clear_state(cid)
                file_bytes = await download_telegram_file(doc["file_id"])
                if not file_bytes:
                    await send_message(cid, "❌ Failed to download file.")
                    return JSONResponse({"ok": True})
                extracted = extract_text_from_txt(file_bytes)
                if not extracted:
                    await send_message(cid, "❌ .txt file is empty.")
                    return JSONResponse({"ok": True})
                set_user_system(cid, extracted)
                await send_message(
                    cid,
                    f"✅ System instructions updated from .txt:\n\n<i>{escape_html(extracted[:500])}</i>",
                    parse_mode="HTML",
                    reply_markup=ikb([[btn("🔙 Back", "back_settings")]]),
                )
                return JSONResponse({"ok": True})
            if st == "awaiting_broadcast" and message.get("voice"):
                clear_state(cid)
                if not is_admin(cid):
                    return JSONResponse({"ok": True})
                voice_data = await download_telegram_file(message["voice"]["file_id"])
                if not voice_data:
                    await send_message(cid, "❌ Failed to download voice message.")
                    return JSONResponse({"ok": True})
                users = get_all_users()
                success, fail = 0, 0
                for uid in users:
                    try:
                        sent = await send_voice_bytes(int(uid), voice_data, "📢 Broadcast voice")
                        await send_message(int(uid), "📢 Voice broadcast from admin", reply_markup=broadcast_reply_keyboard())
                        if sent and sent.get("ok"):
                            success += 1
                        else:
                            fail += 1
                    except Exception:
                        fail += 1
                await send_message(cid, f"📢 Voice broadcast done.\n✅ Sent: {success}\n❌ Failed: {fail}")
                return JSONResponse({"ok": True})

        reply_target = get_reply_state(cid)
        if reply_target is not None and ("text" in message or message.get("voice")):
            clear_reply_state(cid)
            reply_text = message.get("text", "").strip()
            voice_data = await download_telegram_file(message["voice"]["file_id"]) if message.get("voice") else None
            if reply_target == -1:
                if voice_data:
                    for admin_id in ADMINS:
                        await send_voice_bytes(admin_id, voice_data, f"Feedback voice from {name} ({cid})")
                        await send_message(
                            admin_id,
                            f"📬 <b>New Voice Feedback</b>\n\n👤 <b>From:</b> {escape_html(name)}\n🆔 <b>ID:</b> <code>{cid}</code>",
                            parse_mode="HTML",
                            reply_markup=admin_user_reply_keyboard(cid),
                        )
                    await send_message(cid, "✅ Voice feedback sent!")
                    return JSONResponse({"ok": True})
                feedback_msg = (
                    f"📬 <b>New Feedback</b>\n\n"
                    f"👤 <b>From:</b> {escape_html(name)}\n"
                    f"🆔 <b>ID:</b> <code>{cid}</code>\n\n"
                    f"💬 {escape_html(reply_text)}"
                )
                for admin_id in ADMINS:
                    await send_message(admin_id, feedback_msg, parse_mode="HTML", reply_markup=admin_user_reply_keyboard(cid))
                await send_message(cid, "✅ Feedback sent!")
                return JSONResponse({"ok": True})
            if is_admin(cid):
                if voice_data:
                    sent = await send_voice_bytes(reply_target, voice_data, "📩 Voice message from Admin")
                    await send_message(reply_target, "📩 Voice message from Admin", reply_markup=admin_reply_keyboard(reply_target))
                    status = "✅ Sent" if sent and sent.get("ok") else "❌ Failed"
                    await send_message(cid, f"{status} to <code>{reply_target}</code>.", parse_mode="HTML")
                    return JSONResponse({"ok": True})
                admin_msg = f"📩 <b>Message from Admin:</b>\n\n{escape_html(reply_text)}"
                result = await send_message(reply_target, admin_msg, parse_mode="HTML", reply_markup=admin_reply_keyboard(reply_target))
                status = "✅ Sent" if result and result.get("ok") else "❌ Failed"
                await send_message(cid, f"{status} to <code>{reply_target}</code>.", parse_mode="HTML")
                return JSONResponse({"ok": True})
            if voice_data:
                for admin_id in ADMINS:
                    await send_voice_bytes(admin_id, voice_data, f"Voice reply from {name} ({cid})")
                    await send_message(
                        admin_id,
                        f"📩 <b>Voice Reply from User</b>\n\n👤 {escape_html(name)}\n🆔 <code>{cid}</code>",
                        parse_mode="HTML",
                        reply_markup=admin_user_reply_keyboard(cid),
                    )
                await send_message(cid, "✅ Voice reply sent!")
                return JSONResponse({"ok": True})
            user_msg = (
                f"📩 <b>Reply from User</b>\n\n"
                f"👤 {escape_html(name)}\n"
                f"🆔 <code>{cid}</code>\n\n"
                f"💬 {escape_html(reply_text)}"
            )
            for admin_id in ADMINS:
                await send_message(admin_id, user_msg, parse_mode="HTML", reply_markup=admin_user_reply_keyboard(cid))
            await send_message(cid, "✅ Reply sent!")
            return JSONResponse({"ok": True})

        if message.get("photo"):
            await handle_photo(cid, message, name)
            return JSONResponse({"ok": True})

        if message.get("voice"):
            ensure_user(cid, name)
            await handle_voice(cid, message["voice"], name)
            return JSONResponse({"ok": True})

        if message.get("document"):
            await handle_document(cid, message, name)
            return JSONResponse({"ok": True})

        if message.get("audio"):
            await handle_audio(cid, message, name)
            return JSONResponse({"ok": True})

        if message.get("video") or message.get("video_note"):
            await handle_video(cid, message, name)
            return JSONResponse({"ok": True})

        if message.get("animation"):
            await handle_animation(cid, message, name)
            return JSONResponse({"ok": True})

        if message.get("sticker"):
            await handle_sticker(cid, message, name)
            return JSONResponse({"ok": True})

        if "text" not in message:
            await send_message(cid, "⚠️ Unsupported message type. Send text, images, voice, documents, audio, or video.")
            return JSONResponse({"ok": True})

        text = message["text"]

        if text == "/start":
            if user_exists(cid):
                remove_all_user_data(cid)
            save_user(cid, name)
            clear_history(cid)
            set_user_model(cid, "gemini-2.5-flash-lite")
            welcome = (
                f"👋 <b>Hi {escape_html(name)}, Welcome to Mero AI!</b>\n\n"
                f"🤖 <b>Mero</b> is your intelligent AI assistant, optimized with advanced large language models "
                f"to deliver fast, accurate, and context-aware responses.\n\n"
                f"<b>Here's what Mero can do for you:</b>\n\n"
                f"💬 <b>Natural Conversations</b> — Chat naturally on any topic\n"
                f"🌐 <b>Real-time Web Search</b> — Get the most up-to-date information\n"
                f"🎬 <b>YouTube Analysis</b> — Transcribe, summarize &amp; analyze videos\n"
                f"🎨 <b>Image Generation</b> — Create stunning AI-generated images\n"
                f"🖼️ <b>Image Analysis</b> — Upload a photo and get detailed descriptions\n"
                f"🔗 <b>URL Browsing</b> — Browse and analyze any public webpage\n"
                f"📄 <b>Document Processing</b> — Analyze PDFs, DOCX, spreadsheets &amp; more\n"
                f"🎵 <b>Audio &amp; Video</b> — Process audio and video files\n"
                f"💻 <b>Code in 100+ Languages</b> — Write, debug &amp; explain code\n"
                f"🌍 <b>Translation</b> — Translate between languages effortlessly\n"
                f"📊 <b>Math &amp; Science</b> — Solve complex problems step by step\n"
                f"📖 <b>Summarization</b> — Condense long texts into key points\n"
                f"🧠 <b>Memory</b> — Mero remembers your conversations for contextual responses\n"
                f"📋 <b>Custom Instructions</b> — Set system instructions for personalized behavior\n"
                f"🎙️ <b>Voice Responses</b> — Mero can reply with voice (English available)\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"Mero is <b>fast, free, and powerful</b>. With its agentic workflow, "
                f"it understands your intent and routes your requests intelligently.\n\n"
                f"🙏 <i>Thank you for using Mero! If you love it, share it with your friends.</i>"
            )
            await send_message(cid, welcome, parse_mode="HTML", reply_markup=start_keyboard())
            await send_message(
                cid,
                "✍️ <b>Type or speak your prompt — I'm ready to dive in!</b>\n\n"
                "💡 Here are some template prompts to get you started:",
                parse_mode="HTML",
                reply_markup=template_prompts_keyboard(),
            )
            return JSONResponse({"ok": True})

        if text in ("/settings", "/menu"):
            ensure_user(cid, name)
            kb = admin_settings_keyboard() if is_admin(cid) else user_settings_keyboard()
            await send_message(cid, "⚙️ <b>Settings</b>", parse_mode="HTML", reply_markup=kb)
            return JSONResponse({"ok": True})

        if text == "/clear":
            ensure_user(cid, name)
            clear_history(cid)
            await send_message(cid, "🗑️ Conversation cleared.")
            return JSONResponse({"ok": True})

        if text == "/cls":
            ensure_user(cid, name)
            clear_file_data(cid)
            await send_message(cid, "🧹 Last attachment cleared.")
            return JSONResponse({"ok": True})

        if text == "/exit":
            remove_all_user_data(cid)
            await send_message(
                cid,
                "👋 <b>All your data has been cleared.</b>\n\nSend /start to begin fresh.",
                parse_mode="HTML",
            )
            return JSONResponse({"ok": True})

        if text == "/history":
            ensure_user(cid, name)
            history = get_all_history(cid)
            if not history:
                await send_message(cid, "📜 No conversation history.")
                return JSONResponse({"ok": True})
            text_parts = [f"📜 <b>History ({len(history)} messages):</b>\n"]
            for msg in history[-20:]:
                label = "👤 You" if msg["role"] == "user" else "🤖 Mero AI"
                t = msg.get("text", "")[:500]
                text_parts.append(f"<b>{label}:</b>\n{escape_html(t)}\n")
            await send_message(cid, "\n".join(text_parts), parse_mode="HTML")
            return JSONResponse({"ok": True})

        if text == "/total":
            if not is_admin(cid):
                await send_message(cid, "Command not recognized.")
                return JSONResponse({"ok": True})
            users = get_all_users()
            if not users:
                await send_message(cid, "No users.")
                return JSONResponse({"ok": True})
            rows = []
            response_text = f"📊 <b>Total Users: {len(users)}</b>\n\n"
            for uid_str, uname in users.items():
                label = (uname or "User").strip() or "User"
                response_text += f"🆔 <code>{uid_str}</code> — {escape_html(label)}\n"
                if int(uid_str) not in ADMINS:
                    rows.append([
                        btn(f"💬 Message {label[:16]}", f"reply_user:{uid_str}"),
                        btn(f"🚫 Ban {label[:16]}", f"ban_confirm:{uid_str}"),
                    ])
            await send_message(cid, response_text, parse_mode="HTML", reply_markup=ikb(rows))
            return JSONResponse({"ok": True})

        if text.startswith("/sendMessage"):
            if not is_admin(cid):
                await send_message(cid, "Command not recognized.")
                return JSONResponse({"ok": True})
            content = text.replace("/sendMessage", "", 1).strip()
            if " - " not in content:
                await send_message(cid, "Format: /sendMessage &lt;user_id&gt; - &lt;message&gt;", parse_mode="HTML")
                return JSONResponse({"ok": True})
            target_str, msg_content = content.split(" - ", 1)
            target_str = target_str.strip()
            if not target_str.lstrip("-").isdigit():
                await send_message(cid, "Invalid user ID.")
                return JSONResponse({"ok": True})
            target = int(target_str)
            if not user_exists(target):
                await send_message(cid, f"User <code>{target}</code> not found.", parse_mode="HTML")
                return JSONResponse({"ok": True})
            admin_msg = f"📩 <b>Message from Admin:</b>\n\n{escape_html(msg_content.strip())}"
            result = await send_message(target, admin_msg, parse_mode="HTML", reply_markup=admin_reply_keyboard(target))
            status = "✅ Sent" if result and result.get("ok") else "❌ Failed"
            await send_message(cid, f"{status} to <code>{target}</code>.", parse_mode="HTML")
            return JSONResponse({"ok": True})

        if text.startswith("/broadcast"):
            if not is_admin(cid):
                await send_message(cid, "Command not recognized.")
                return JSONResponse({"ok": True})
            broadcast_msg = text.replace("/broadcast", "", 1).strip()
            if not broadcast_msg:
                await send_message(cid, "Provide a message after /broadcast.")
                return JSONResponse({"ok": True})
            users = get_all_users()
            success, fail = 0, 0
            for uid in users:
                try:
                    result = await send_message(
                        int(uid),
                        f"📢 <b>Broadcast:</b>\n\n{escape_html(broadcast_msg)}",
                        parse_mode="HTML",
                        reply_markup=broadcast_reply_keyboard(),
                    )
                    if result and result.get("ok"):
                        success += 1
                    else:
                        fail += 1
                except Exception:
                    fail += 1
            await send_message(cid, f"📢 Done.\n✅ Sent: {success}\n❌ Failed: {fail}")
            return JSONResponse({"ok": True})

        if text.startswith("/ban"):
            if not is_admin(cid):
                await send_message(cid, "Command not recognized.")
                return JSONResponse({"ok": True})
            target_str = text.replace("/ban", "", 1).strip()
            if not target_str.lstrip("-").isdigit():
                await send_message(cid, "Format: /ban &lt;user_id&gt;", parse_mode="HTML")
                return JSONResponse({"ok": True})
            target = int(target_str)
            uname = get_all_users().get(str(target), "Unknown")
            ban_user(target, uname)
            await send_message(cid, f"🚫 Banned <code>{target}</code> ({escape_html(uname)})", parse_mode="HTML")
            await send_message(target, "🚫 You have been banned from using this bot.")
            return JSONResponse({"ok": True})

        if text.startswith("/unban"):
            if not is_admin(cid):
                await send_message(cid, "Command not recognized.")
                return JSONResponse({"ok": True})
            target_str = text.replace("/unban", "", 1).strip()
            if not target_str.lstrip("-").isdigit():
                await send_message(cid, "Format: /unban &lt;user_id&gt;", parse_mode="HTML")
                return JSONResponse({"ok": True})
            target = int(target_str)
            unban_user(target)
            await send_message(cid, f"✅ Unbanned <code>{target}</code>", parse_mode="HTML")
            await send_message(target, "🎉 You have been unbanned! Send /start to continue.")
            return JSONResponse({"ok": True})

        if text.startswith("/feedback"):
            ensure_user(cid, name)
            feedback_text = text.replace("/feedback", "", 1).strip()
            if not feedback_text:
                set_reply_state(cid, -1)
                await send_message(cid, "💬 Type your feedback or send voice:", reply_markup=ikb([[btn("❌ Cancel", "cancel_reply")]]))
                return JSONResponse({"ok": True})
            feedback_msg = (
                f"📬 <b>New Feedback</b>\n\n"
                f"👤 {escape_html(name)}\n"
                f"🆔 <code>{cid}</code>\n\n"
                f"💬 {escape_html(feedback_text)}"
            )
            for admin_id in ADMINS:
                await send_message(admin_id, feedback_msg, parse_mode="HTML", reply_markup=admin_user_reply_keyboard(cid))
            await send_message(cid, "✅ Feedback sent!")
            return JSONResponse({"ok": True})

        if text == "/clear_system":
            ensure_user(cid, name)
            clear_user_system(cid)
            await send_message(cid, "🗑️ System instructions cleared.")
            return JSONResponse({"ok": True})

        if text == "/help":
            ensure_user(cid, name)
            help_text = (
                "📖 <b>Mero AI Commands</b>\n\n"
                "/start — Restart the bot\n"
                "/settings — Open settings menu\n"
                "/clear — Clear chat history\n"
                "/cls — Clear last attachment\n"
                "/exit — Clear all data and restart\n"
                "/history — View chat history\n"
                "/feedback — Send feedback to admin\n"
                "/clear_system — Clear system instructions\n"
                "/help — Show this help message\n\n"
                "<b>How to use:</b>\n"
                "• Send text to chat\n"
                "• Send images for analysis\n"
                "• Send voice messages (up to 5 min)\n"
                "• Send documents (PDF, DOCX, code files, etc.)\n"
                "• Send audio/video files\n"
                "• Send YouTube links for video analysis\n"
                "• Ask to generate images\n"
            )
            await send_message(cid, help_text, parse_mode="HTML")
            return JSONResponse({"ok": True})

        if text.startswith("/"):
            await send_message(cid, "Command not recognized. Use /help to see available commands.")
            return JSONResponse({"ok": True})

        if not user_exists(cid):
            save_user(cid, name)
            welcome = (
                f"👋 <b>Hi {escape_html(name)}, Welcome to Mero AI!</b>\n\n"
                f"Send /start for the full introduction, or just keep chatting!"
            )
            await send_message(cid, welcome, parse_mode="HTML", reply_markup=start_keyboard())

        ensure_user(cid, name)
        await send_chat_action(cid, "typing")
        await agent_route(cid, text.strip(), name)
        return JSONResponse({"ok": True})

    except Exception:
        return JSONResponse({"ok": True})
