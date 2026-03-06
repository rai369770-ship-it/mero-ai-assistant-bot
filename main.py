from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import httpx
import urllib.parse
import json
import re
import os
import redis
import base64

app = FastAPI()

BOT_TOKEN = "8655216165:AAEoDExRbxAmZVxGL9H0na4hziBEv6I-0RA"
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
POOL_API = "https://sr-pool-api-5bm.pages.dev"
MODEL = "gemini-2.5-flash"
ADMIN_ID = 7026190306

REDIS_URL = os.environ.get("REDIS_URL", "")
r = redis.from_url(REDIS_URL, decode_responses=True)

api_keys = []

MAX_HISTORY = 10
CONTEXT_SIZE = 5

image_store = {}


def get_system_text(name):
    return (
        f"You're Mero AI assistant developed by Sujan Rai. "
        f"User's name: {name}. "
        f"You can analyze YouTube videos, generate images, answer questions, search the web, "
        f"browse URLs, write code, translate languages, summarize text, solve math problems, "
        f"analyze images, transcribe voice messages, and have natural conversations. "
        f"Always provide helpful, accurate, and well-structured responses. "
        f"You can show emotions. You have emotions. if user sends you voice message, transcribe and reply like a normal."
    )


def get_history_key(chat_id):
    return f"chat:{chat_id}:history"


def save_user(user_id, name):
    r.hset("totalUsers", str(user_id), name)


def user_exists(user_id):
    return r.hexists("totalUsers", str(user_id))


def remove_user(user_id):
    r.hdel("totalUsers", str(user_id))
    r.delete(get_history_key(user_id))
    if str(user_id) in image_store:
        del image_store[str(user_id)]


def get_all_users():
    return r.hgetall("totalUsers")


def save_message(chat_id, role, text):
    key = get_history_key(chat_id)
    count = r.llen(key)
    if count >= MAX_HISTORY * 2:
        r.ltrim(key, -((MAX_HISTORY - 1) * 2), -1)
    entry = json.dumps({"role": role, "text": text})
    r.rpush(key, entry)


def get_all_history(chat_id):
    key = get_history_key(chat_id)
    items = r.lrange(key, 0, -1)
    return [json.loads(item) for item in items]


def get_recent_history(chat_id, count=CONTEXT_SIZE):
    key = get_history_key(chat_id)
    total = r.llen(key)
    if total == 0:
        return []
    pair_count = count * 2
    start = max(0, total - pair_count)
    items = r.lrange(key, start, -1)
    return [json.loads(item) for item in items]


def clear_history(chat_id):
    r.delete(get_history_key(chat_id))


def escape_html(text):
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text


def markdown_to_html(text):
    lines = text.split("\n")
    result = []
    in_code_block = False
    code_lang = ""
    code_lines = []

    for line in lines:
        if not in_code_block and re.match(r"^```(\w*)", line):
            in_code_block = True
            code_lang = re.match(r"^```(\w*)", line).group(1)
            code_lines = []
            continue
        if in_code_block and line.strip() == "```":
            in_code_block = False
            code_content = escape_html("\n".join(code_lines))
            result.append(f"<pre>{code_content}</pre>")
            continue
        if in_code_block:
            code_lines.append(line)
            continue

        processed = escape_html(line)
        processed = re.sub(r"`([^`]+)`", r"<code>\1</code>", processed)
        processed = re.sub(r"\*\*\*(.+?)\*\*\*", r"<b><i>\1</i></b>", processed)
        processed = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", processed)
        processed = re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"<i>\1</i>", processed)
        processed = re.sub(r"__(.+?)__", r"<u>\1</u>", processed)
        processed = re.sub(r"~~(.+?)~~", r"<s>\1</s>", processed)
        processed = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', processed)
        result.append(processed)

    if in_code_block:
        code_content = escape_html("\n".join(code_lines))
        result.append(f"<pre>{code_content}</pre>")

    return "\n".join(result)


async def send_message(chat_id, text, parse_mode=None):
    url = f"{TELEGRAM_API}/sendMessage"
    chunks = [text[i:i + 4096] for i in range(0, len(text), 4096)]
    result = None
    async with httpx.AsyncClient(timeout=30.0) as client:
        for chunk in chunks:
            payload = {"chat_id": chat_id, "text": chunk}
            if parse_mode:
                payload["parse_mode"] = parse_mode
            response = await client.post(url, json=payload)
            result = response.json()
            if not result.get("ok") and parse_mode:
                payload.pop("parse_mode", None)
                response = await client.post(url, json=payload)
                result = response.json()
    return result


async def send_photo(chat_id, photo_url, caption=None):
    url = f"{TELEGRAM_API}/sendPhoto"
    payload = {"chat_id": chat_id, "photo": photo_url}
    if caption:
        payload["caption"] = caption
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, json=payload)
        return response.json()


async def download_telegram_file(file_id):
    async with httpx.AsyncClient(timeout=60.0) as client:
        file_info_resp = await client.get(f"{TELEGRAM_API}/getFile?file_id={file_id}")
        file_info = file_info_resp.json()
        if not file_info.get("ok"):
            return None
        file_path = file_info["result"]["file_path"]
        download_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        file_resp = await client.get(download_url)
        if file_resp.status_code == 200:
            return file_resp.content
        return None


async def fetch_api_keys():
    global api_keys
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(POOL_API)
        if response.status_code == 200:
            keys = response.json()
            if isinstance(keys, list) and len(keys) > 0:
                api_keys = keys
                return True
    return False


async def try_api_call(body_json, tried=None):
    global api_keys
    if tried is None:
        tried = set()
    key_index = None
    for i in range(len(api_keys)):
        if i not in tried:
            key_index = i
            break
    if key_index is None:
        return None, "All API keys exhausted"
    tried.add(key_index)
    key = api_keys[key_index]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={key}"
    headers = {"Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(url, content=body_json, headers=headers)
        if response.status_code == 200:
            return response.text, None
        for i in range(len(api_keys)):
            if i not in tried:
                return await try_api_call(body_json, tried)
        return None, f"API error {response.status_code}"


def build_body(history_messages, current_parts, system_text, use_tools=True):
    contents = []
    for msg in history_messages:
        role = "user" if msg["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": msg.get("text", "")}]})
    contents.append({"role": "user", "parts": current_parts})

    body = {
        "system_instruction": {"parts": [{"text": system_text}]},
        "contents": contents,
        "generationConfig": {"maxOutputTokens": 65536}
    }

    if use_tools:
        body["tools"] = [{"google_search": {}}, {"url_context": {}}]

    return body


def extract_sources(data):
    sources = []
    seen = set()
    try:
        candidates = data.get("candidates", [])
        if not candidates:
            return sources
        candidate = candidates[0]
        grounding = candidate.get("groundingMetadata")
        if not grounding:
            return sources
        chunks = grounding.get("groundingChunks", [])
        for chunk in chunks:
            web = chunk.get("web")
            if not web:
                continue
            uri = web.get("uri", "")
            title = web.get("title", "Source")
            if uri and uri not in seen:
                seen.add(uri)
                sources.append({"title": title.strip(), "url": uri.strip()})
    except Exception:
        pass
    return sources


def extract_ai_text(content):
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return "Failed to parse AI response.", []

    candidates = data.get("candidates", [])
    if not candidates:
        return "No response received from AI.", []

    candidate = candidates[0]
    parts = candidate.get("content", {}).get("parts", [])
    ai_text = ""
    for p in parts:
        if p.get("text"):
            if ai_text:
                ai_text += "\n"
            ai_text += p["text"]

    if not ai_text:
        return "No response received from AI.", []

    sources = extract_sources(data)
    return ai_text, sources


def format_response_with_sources(ai_text, sources):
    html_text = markdown_to_html(ai_text)
    if not sources:
        return html_text
    html_text += "\n\n📌 <b>Sources:</b>\n"
    for s in sources:
        title = escape_html(s["title"])
        url = s["url"]
        html_text += f'• <a href="{url}">{title}</a>\n'
    return html_text


def get_user_name(message):
    user = message.get("from", {})
    first = user.get("first_name", "")
    last = user.get("last_name", "")
    name = f"{first} {last}".strip()
    if not name:
        name = user.get("username", "User")
    return name


def ensure_user(chat_id, name):
    if not user_exists(chat_id):
        save_user(chat_id, name)


async def handle_gemini(chat_id, current_parts, system_text, use_tools=True):
    history = get_recent_history(chat_id, CONTEXT_SIZE)
    body = build_body(history, current_parts, system_text, use_tools)
    json_body = json.dumps(body)

    success = await fetch_api_keys()
    if not success:
        error_msg = "Could not fetch API keys. Please try again later."
        save_message(chat_id, "model", error_msg)
        await send_message(chat_id, error_msg)
        return

    content, err = await try_api_call(json_body)
    if content:
        ai_text, sources = extract_ai_text(content)
        if ai_text and ai_text not in ("No response received from AI.", "Failed to parse AI response."):
            save_message(chat_id, "model", ai_text)
            formatted = format_response_with_sources(ai_text, sources)
            await send_message(chat_id, formatted, parse_mode="HTML")
        else:
            save_message(chat_id, "model", ai_text)
            await send_message(chat_id, ai_text)
    else:
        error = f"Error: {err or 'Unknown error occurred'}"
        save_message(chat_id, "model", error)
        await send_message(chat_id, error)


@app.get("/")
async def home():
    return {"status": "ok", "message": "Mero AI Assistant Bot is running!"}


@app.post("/webhook")
async def webhook(request: Request):
    try:
        data = await request.json()
        if "message" not in data:
            return JSONResponse({"ok": True})

        message = data["message"]
        chat_id = message["chat"]["id"]
        name = get_user_name(message)

        if message.get("video") or message.get("video_note") or message.get("document") or message.get("audio") or message.get("animation") or message.get("sticker"):
            await send_message(chat_id, "⚠️ This attachment type is not supported right now. You can upload images or send voice messages instead.")
            return JSONResponse({"ok": True})

        if message.get("photo"):
            ensure_user(chat_id, name)
            photo_list = message["photo"]
            best_photo = photo_list[-1]
            file_id = best_photo["file_id"]
            caption = message.get("caption", "").strip()
            if not caption:
                caption = "Describe this image in detail."

            await send_message(chat_id, "🖼️ Analyzing image...")

            image_data = await download_telegram_file(file_id)
            if not image_data:
                await send_message(chat_id, "Failed to download the image. Please try again.")
                return JSONResponse({"ok": True})

            encoded = base64.b64encode(image_data).decode("utf-8")
            image_store[str(chat_id)] = encoded

            save_message(chat_id, "user", f"[Image] {caption}")

            parts = [
                {"text": caption},
                {"inlineData": {"mimeType": "image/jpeg", "data": encoded}}
            ]

            system_text = get_system_text(name)
            await handle_gemini(chat_id, parts, system_text, use_tools=False)
            return JSONResponse({"ok": True})

        if message.get("voice"):
            ensure_user(chat_id, name)
            voice = message["voice"]
            duration = voice.get("duration", 0)

            if duration > 300:
                await send_message(chat_id, "⚠️ Sorry, the voice message can only be recorded up to 5 minutes.")
                return JSONResponse({"ok": True})

            file_id = voice["file_id"]
            mime_type = voice.get("mime_type", "audio/ogg")

            await send_message(chat_id, "🎙️ Processing voice message...")

            voice_data = await download_telegram_file(file_id)
            if not voice_data:
                await send_message(chat_id, "Failed to download the voice message. Please try again.")
                return JSONResponse({"ok": True})

            encoded_voice = base64.b64encode(voice_data).decode("utf-8")

            save_message(chat_id, "user", "[Voice Message]")

            prompt = "Transcribe this voice message, analyze it, and reply to it."

            parts = [
                {"text": prompt},
                {"inlineData": {"mimeType": mime_type, "data": encoded_voice}}
            ]

            system_text = get_system_text(name)
            await handle_gemini(chat_id, parts, system_text, use_tools=False)
            return JSONResponse({"ok": True})

        if "text" not in message:
            return JSONResponse({"ok": True})

        text = message["text"]

        if text == "/start":
            if user_exists(chat_id):
                await send_message(
                    chat_id,
                    "👋 You're already using this bot! Type anything to continue chatting or /clear to start fresh.",
                    parse_mode="HTML"
                )
                return JSONResponse({"ok": True})

            save_user(chat_id, name)
            clear_history(chat_id)
            welcome = (
                "✨ <b>Welcome to Mero AI Assistant!</b> ✨\n\n"
                f"Hello, <b>{escape_html(name)}</b>! 🎉\n\n"
                "Your intelligent companion powered by <b>Gemini Multimodal</b> ⚡\n\n"
                "<b>Here's what I can do:</b>\n\n"
                "💬 <b>Chat</b> — Just type anything to start a conversation\n"
                "🖼️ <b>Image Analysis</b> — Send an image with or without a caption\n"
                "🎙️ <b>Voice Messages</b> — Send a voice message (up to 5 min)\n"
                "🎬 <b>YouTube Analysis</b> — <code>/youtube &lt;url&gt;</code> or <code>/youtube &lt;url&gt; &lt;prompt&gt;</code>\n"
                "🎨 <b>Image Generation</b> — <code>/imagine &lt;description&gt;</code>\n"
                "🌐 <b>Web Search</b> — Automatically searches when needed\n"
                "🔗 <b>URL Browsing</b> — Send any URL to get a summary\n"
                "📝 <b>Code Writing</b> — Ask me to write code in any language\n"
                "🌍 <b>Translation</b> — Translate text between languages\n"
                "📊 <b>Math &amp; Science</b> — Solve equations and explain concepts\n"
                "📖 <b>Summarization</b> — Summarize articles, documents, or text\n"
                "📜 <b>Chat History</b> — <code>/history</code> to view your conversation\n"
                "🗑️ <b>Clear Chat</b> — <code>/clear</code> to start fresh\n"
                "🧹 <b>Clear Image</b> — <code>/cls</code> to clear stored image\n"
                "💬 <b>Feedback</b> — <code>/feedback &lt;your feedback&gt;</code> to send feedback to admin\n"
                "🚪 <b>Exit</b> — <code>/exit</code> to remove your data\n\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "I remember your last 5 conversations for context.\n"
                "Up to 10 messages are stored in history.\n\n"
                "🚀 <i>Developed by Sujan Rai</i>"
            )
            await send_message(chat_id, welcome, parse_mode="HTML")
            return JSONResponse({"ok": True})

        if text == "/exit":
            if not user_exists(chat_id):
                await send_message(chat_id, "You are not registered. Send /start first.")
                return JSONResponse({"ok": True})
            remove_user(chat_id)
            await send_message(
                chat_id,
                "🚪 You have exited the bot successfully. Thanks for your support! Send /start anytime to come back.",
                parse_mode="HTML"
            )
            return JSONResponse({"ok": True})

        if text == "/clear":
            ensure_user(chat_id, name)
            clear_history(chat_id)
            await send_message(chat_id, "🗑️ Conversation cleared.", parse_mode="HTML")
            return JSONResponse({"ok": True})

        if text == "/cls":
            ensure_user(chat_id, name)
            if str(chat_id) in image_store:
                del image_store[str(chat_id)]
            await send_message(chat_id, "🧹 Stored image cleared.", parse_mode="HTML")
            return JSONResponse({"ok": True})

        if text == "/history":
            ensure_user(chat_id, name)
            history = get_all_history(chat_id)
            if not history:
                await send_message(chat_id, "📜 No conversation history found.")
                return JSONResponse({"ok": True})

            await send_message(chat_id, f"📜 <b>Your Conversation History ({len(history)} messages):</b>", parse_mode="HTML")

            for msg in history:
                role_label = "👤 You" if msg["role"] == "user" else "🤖 Mero AI"
                msg_text = msg.get("text", "")
                if len(msg_text) > 3000:
                    msg_text = msg_text[:3000] + "..."
                formatted = f"<b>{role_label}:</b>\n{escape_html(msg_text)}"
                await send_message(chat_id, formatted, parse_mode="HTML")

            return JSONResponse({"ok": True})

        if text == "/total":
            if chat_id != ADMIN_ID:
                await send_message(chat_id, "The command was not recognized.")
                return JSONResponse({"ok": True})
            users = get_all_users()
            total = len(users)
            response_text = f"📊 <b>Total Users: {total}</b>\n\n"
            for uid, uname in users.items():
                response_text += f"🆔 <code>{uid}</code> — {escape_html(uname)}\n"
            if not users:
                response_text += "No users registered yet."
            await send_message(chat_id, response_text, parse_mode="HTML")
            return JSONResponse({"ok": True})

        if text.startswith("/sendMessage"):
            if chat_id != ADMIN_ID:
                await send_message(chat_id, "The command was not recognized.")
                return JSONResponse({"ok": True})
            content = text.replace("/sendMessage", "", 1).strip()
            if " - " not in content:
                await send_message(chat_id, "Format: /sendMessage &lt;user_id&gt; - &lt;message&gt;", parse_mode="HTML")
                return JSONResponse({"ok": True})
            parts = content.split(" - ", 1)
            target_id = parts[0].strip()
            msg_content = parts[1].strip()
            if not target_id.lstrip("-").isdigit():
                await send_message(chat_id, "Invalid user ID.")
                return JSONResponse({"ok": True})
            if not user_exists(int(target_id)):
                await send_message(chat_id, f"User <code>{target_id}</code> does not exist in the database.", parse_mode="HTML")
                return JSONResponse({"ok": True})
            try:
                result = await send_message(int(target_id), f"📩 <b>Message from Admin:</b>\n\n{msg_content}", parse_mode="HTML")
                if result and result.get("ok"):
                    await send_message(chat_id, f"✅ Message sent to <code>{target_id}</code>.", parse_mode="HTML")
                else:
                    await send_message(chat_id, f"❌ Failed to send message to <code>{target_id}</code>.", parse_mode="HTML")
            except Exception:
                await send_message(chat_id, f"❌ Error sending message to <code>{target_id}</code>.", parse_mode="HTML")
            return JSONResponse({"ok": True})

        if text.startswith("/broadcast"):
            if chat_id != ADMIN_ID:
                await send_message(chat_id, "The command was not recognized.")
                return JSONResponse({"ok": True})
            broadcast_msg = text.replace("/broadcast", "", 1).strip()
            if not broadcast_msg:
                await send_message(chat_id, "Please provide a message after /broadcast.")
                return JSONResponse({"ok": True})
            users = get_all_users()
            success_count = 0
            fail_count = 0
            broadcast_text = f"Messages for all users by admin: {broadcast_msg}"
            for uid in users:
                try:
                    result = await send_message(int(uid), broadcast_text)
                    if result and result.get("ok"):
                        success_count += 1
                    else:
                        fail_count += 1
                except Exception:
                    fail_count += 1
            await send_message(chat_id, f"📢 Broadcast complete.\n✅ Sent: {success_count}\n❌ Failed: {fail_count}", parse_mode="HTML")
            return JSONResponse({"ok": True})

        if text.startswith("/feedback"):
            ensure_user(chat_id, name)
            feedback_text = text.replace("/feedback", "", 1).strip()
            if not feedback_text:
                await send_message(chat_id, "Please provide your feedback after /feedback.\n\nExample: <code>/feedback This bot is amazing!</code>", parse_mode="HTML")
                return JSONResponse({"ok": True})
            feedback_message = (
                f"📬 <b>New Feedback Received</b>\n\n"
                f"👤 <b>From:</b> {escape_html(name)}\n"
                f"🆔 <b>User ID:</b> <code>{chat_id}</code>\n\n"
                f"💬 <b>Feedback:</b>\n{escape_html(feedback_text)}"
            )
            try:
                result = await send_message(ADMIN_ID, feedback_message, parse_mode="HTML")
                if result and result.get("ok"):
                    await send_message(chat_id, "✅ Your feedback has been sent to the admin. Thank you!", parse_mode="HTML")
                else:
                    await send_message(chat_id, "❌ Failed to send your feedback. Please try again later.")
            except Exception:
                await send_message(chat_id, "❌ An error occurred while sending your feedback. Please try again later.")
            return JSONResponse({"ok": True})

        if text.startswith("/imagine"):
            ensure_user(chat_id, name)
            prompt = text.replace("/imagine", "", 1).strip()
            if not prompt:
                await send_message(chat_id, "Please provide an image description after /imagine.")
                return JSONResponse({"ok": True})

            await send_message(chat_id, "🎨 Generating image...")

            encoded_prompt = urllib.parse.quote(prompt)
            image_api_url = f"https://yabes-api.pages.dev/api/ai/image/dalle?prompt={encoded_prompt}"

            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.get(image_api_url)
                    if response.status_code == 200:
                        resp_data = response.json()
                        if resp_data.get("success") and "output" in resp_data:
                            await send_photo(chat_id, resp_data["output"], f"🎨 {prompt}")
                            save_message(chat_id, "user", f"/imagine {prompt}")
                            save_message(chat_id, "model", f"Generated image for: {prompt}")
                        else:
                            await send_message(chat_id, "Image generation failed. Please try again.")
                    else:
                        await send_message(chat_id, f"Image API error: {response.status_code}")
            except Exception as e:
                await send_message(chat_id, f"Image generation error: {str(e)}")

            return JSONResponse({"ok": True})

        if text.startswith("/youtube"):
            ensure_user(chat_id, name)
            yt_input = text.replace("/youtube", "", 1).strip()
            if not yt_input:
                await send_message(chat_id, "Please provide a YouTube URL after /youtube.")
                return JSONResponse({"ok": True})

            parts = yt_input.split(None, 1)
            yt_url = parts[0]
            prompt = parts[1] if len(parts) > 1 else "Analyze this YouTube video in detail."

            await send_message(chat_id, "🎬 Processing video...")

            user_text = f"{prompt} [YouTube: {yt_url}]"
            save_message(chat_id, "user", user_text)

            current_parts = [
                {"text": prompt},
                {"fileData": {"mimeType": "video/mp4", "fileUri": yt_url}}
            ]

            system_text = get_system_text(name)
            await handle_gemini(chat_id, current_parts, system_text, use_tools=False)
            return JSONResponse({"ok": True})

        if text.startswith("/"):
            await send_message(chat_id, "The command was not recognized. Type /start to see available commands.")
            return JSONResponse({"ok": True})

        ensure_user(chat_id, name)
        trimmed = text.strip()

        await send_message(chat_id, "🤖 Thinking...")

        save_message(chat_id, "user", trimmed)

        current_parts = [{"text": trimmed}]

        stored_image = image_store.get(str(chat_id))
        if stored_image:
            current_parts.append({"inlineData": {"mimeType": "image/jpeg", "data": stored_image}})

        system_text = get_system_text(name)
        use_tools = stored_image is None
        await handle_gemini(chat_id, current_parts, system_text, use_tools=use_tools)

        return JSONResponse({"ok": True})

    except Exception:
        return JSONResponse({"ok": True})