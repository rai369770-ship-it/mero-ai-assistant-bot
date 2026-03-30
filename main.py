from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import httpx
import urllib.parse
import json
import re
import os
import redis
import base64
from typing import Optional

app = FastAPI()

BOT_TOKEN = "8655216165:AAEoDExRbxAmZVxGL9H0na4hziBEv6I-0RA"
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
POOL_API = "https://sr-pool-api-5bm.pages.dev"
MODEL = "gemini-2.5-flash-light"
ADMIN_ID = 7026190306

REDIS_URL = os.environ.get("REDIS_URL", "")
r = redis.from_url(REDIS_URL, decode_responses=True)

api_keys: list[str] = []
image_store: dict[str, str] = {}

MAX_HISTORY = 30
CONTEXT_SIZE = 30

AGENT_PROMPT = """Analyze the user prompt.
Return the exact functions only in python.
functions and intensions.
sendNormalMessage(query).
Sends normal message. The last query is already stored in my query variable.
sendYouTube(prompt, url).
These are not stored in my variables. So, extract prompt and url from user prompt and pass to the function properly. use this function if user gives YouTube link and prompt.
generateImage(query).
The last query is already stored in my query variable.
Understand the user prompt and pass functions properly.
Never write anything else except function.
User prompt: {user_prompt}"""


def get_system_text(name: str) -> str:
    return (
        f"You're Mero AI assistant developed by Sujan Rai. "
        f"User's name: {name}. "
        f"You can analyze YouTube videos, generate images, answer questions, search the web, "
        f"browse URLs, write code, translate languages, summarize text, solve math problems, "
        f"analyze images, transcribe voice messages, and have natural conversations. "
        f"Always provide helpful, accurate, and well-structured responses. "
        f"You can show emotions. You have emotions. If user sends you voice message, transcribe and reply like a normal."
    )


def history_key(chat_id: int) -> str:
    return f"chat:{chat_id}:history"


def reply_state_key(chat_id: int) -> str:
    return f"chat:{chat_id}:reply_state"


def save_user(user_id: int, name: str) -> None:
    r.hset("totalUsers", str(user_id), name)


def user_exists(user_id: int) -> bool:
    return r.hexists("totalUsers", str(user_id))


def remove_user(user_id: int) -> None:
    r.hdel("totalUsers", str(user_id))
    r.delete(history_key(user_id))
    r.delete(reply_state_key(user_id))
    image_store.pop(str(user_id), None)


def get_all_users() -> dict[str, str]:
    return r.hgetall("totalUsers")


def save_message(chat_id: int, role: str, text: str) -> None:
    key = history_key(chat_id)
    if r.llen(key) >= MAX_HISTORY * 2:
        r.ltrim(key, -((MAX_HISTORY - 1) * 2), -1)
    r.rpush(key, json.dumps({"role": role, "text": text}))


def get_all_history(chat_id: int) -> list[dict]:
    return [json.loads(item) for item in r.lrange(history_key(chat_id), 0, -1)]


def get_recent_history(chat_id: int, count: int = CONTEXT_SIZE) -> list[dict]:
    key = history_key(chat_id)
    total = r.llen(key)
    if total == 0:
        return []
    start = max(0, total - count * 2)
    return [json.loads(item) for item in r.lrange(key, start, -1)]


def clear_history(chat_id: int) -> None:
    r.delete(history_key(chat_id))


def set_reply_state(chat_id: int, target_id: int) -> None:
    r.set(reply_state_key(chat_id), str(target_id), ex=3600)


def get_reply_state(chat_id: int) -> Optional[int]:
    val = r.get(reply_state_key(chat_id))
    return int(val) if val else None


def clear_reply_state(chat_id: int) -> None:
    r.delete(reply_state_key(chat_id))


def ensure_user(chat_id: int, name: str) -> None:
    if not user_exists(chat_id):
        save_user(chat_id, name)


def escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def markdown_to_html(text: str) -> str:
    lines = text.split("\n")
    result, code_lines = [], []
    in_code_block, code_lang = False, ""

    for line in lines:
        if not in_code_block and (m := re.match(r"^```(\w*)", line)):
            in_code_block, code_lang, code_lines = True, m.group(1), []
            continue
        if in_code_block and line.strip() == "```":
            in_code_block = False
            result.append(f"<pre>{escape_html(chr(10).join(code_lines))}</pre>")
            continue
        if in_code_block:
            code_lines.append(line)
            continue

        p = escape_html(line)
        for pattern, repl in [
            (r"`([^`]+)`", r"<code>\1</code>"),
            (r"\*\*\*(.+?)\*\*\*", r"<b><i>\1</i></b>"),
            (r"\*\*(.+?)\*\*", r"<b>\1</b>"),
            (r"(?<!\*)\*([^*]+?)\*(?!\*)", r"<i>\1</i>"),
            (r"__(.+?)__", r"<u>\1</u>"),
            (r"~~(.+?)~~", r"<s>\1</s>"),
            (r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>'),
        ]:
            p = re.sub(pattern, repl, p)
        result.append(p)

    if in_code_block:
        result.append(f"<pre>{escape_html(chr(10).join(code_lines))}</pre>")

    return "\n".join(result)


async def send_message(chat_id: int, text: str, parse_mode: Optional[str] = None, reply_markup: Optional[dict] = None) -> Optional[dict]:
    chunks = [text[i:i + 4096] for i in range(0, len(text), 4096)]
    result = None
    async with httpx.AsyncClient(timeout=30.0) as client:
        for chunk in chunks:
            payload = {"chat_id": chat_id, "text": chunk}
            if parse_mode:
                payload["parse_mode"] = parse_mode
            if reply_markup:
                payload["reply_markup"] = reply_markup
            resp = await client.post(f"{TELEGRAM_API}/sendMessage", json=payload)
            result = resp.json()
            if not result.get("ok") and parse_mode:
                payload.pop("parse_mode", None)
                resp = await client.post(f"{TELEGRAM_API}/sendMessage", json=payload)
                result = resp.json()
    return result


async def send_photo(chat_id: int, photo_url: str, caption: Optional[str] = None) -> dict:
    payload = {"chat_id": chat_id, "photo": photo_url}
    if caption:
        payload["caption"] = caption
    async with httpx.AsyncClient(timeout=60.0) as client:
        return (await client.post(f"{TELEGRAM_API}/sendPhoto", json=payload)).json()


async def download_telegram_file(file_id: str) -> Optional[bytes]:
    async with httpx.AsyncClient(timeout=60.0) as client:
        info = (await client.get(f"{TELEGRAM_API}/getFile?file_id={file_id}")).json()
        if not info.get("ok"):
            return None
        resp = await client.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{info['result']['file_path']}")
        return resp.content if resp.status_code == 200 else None


async def fetch_api_keys() -> bool:
    global api_keys
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(POOL_API)
        if resp.status_code == 200:
            keys = resp.json()
            if isinstance(keys, list) and keys:
                api_keys = keys
                return True
    return False


async def try_api_call(body_json: str, tried: Optional[set] = None) -> tuple[Optional[str], Optional[str]]:
    tried = tried or set()
    key_index = next((i for i in range(len(api_keys)) if i not in tried), None)
    if key_index is None:
        return None, "All API keys exhausted"
    tried.add(key_index)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={api_keys[key_index]}"
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(url, content=body_json, headers={"Content-Type": "application/json"})
        if resp.status_code == 200:
            return resp.text, None
        remaining = [i for i in range(len(api_keys)) if i not in tried]
        if remaining:
            return await try_api_call(body_json, tried)
        return None, f"API error {resp.status_code}"


def build_body(history_messages: list[dict], current_parts: list[dict], system_text: str, use_tools: bool = True) -> dict:
    contents = [
        {"role": "user" if msg["role"] == "user" else "model", "parts": [{"text": msg.get("text", "")}]}
        for msg in history_messages
    ]
    contents.append({"role": "user", "parts": current_parts})

    body = {
        "system_instruction": {"parts": [{"text": system_text}]},
        "contents": contents,
        "generationConfig": {"maxOutputTokens": 65536},
    }
    if use_tools:
        body["tools"] = [{"google_search": {}}, {"url_context": {}}]
    return body


def extract_sources(data: dict) -> list[dict]:
    sources, seen = [], set()
    try:
        for chunk in data.get("candidates", [{}])[0].get("groundingMetadata", {}).get("groundingChunks", []):
            web = chunk.get("web", {})
            uri, title = web.get("uri", ""), web.get("title", "Source")
            if uri and uri not in seen:
                seen.add(uri)
                sources.append({"title": title.strip(), "url": uri.strip()})
    except Exception:
        pass
    return sources


def extract_ai_text(content: str) -> tuple[str, list[dict]]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return "Failed to parse AI response.", []

    candidates = data.get("candidates", [])
    if not candidates:
        return "No response received from AI.", []

    parts = candidates[0].get("content", {}).get("parts", [])
    ai_text = "\n".join(p["text"] for p in parts if p.get("text"))
    return (ai_text or "No response received from AI."), extract_sources(data)


def format_response_with_sources(ai_text: str, sources: list[dict]) -> str:
    html = markdown_to_html(ai_text)
    if sources:
        html += "\n\n📌 <b>Sources:</b>\n"
        html += "".join(f'• <a href="{s["url"]}">{escape_html(s["title"])}</a>\n' for s in sources)
    return html


def get_user_name(message: dict) -> str:
    user = message.get("from", {})
    name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
    return name or user.get("username", "User")


async def call_gemini_raw(parts: list[dict], system_text: str) -> Optional[str]:
    if not await fetch_api_keys():
        return None
    body = {
        "system_instruction": {"parts": [{"text": system_text}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"maxOutputTokens": 1024},
    }
    content, _ = await try_api_call(json.dumps(body))
    if not content:
        return None
    text, _ = extract_ai_text(content)
    return text


async def handle_gemini(chat_id: int, current_parts: list[dict], system_text: str, use_tools: bool = True) -> None:
    history = get_recent_history(chat_id, CONTEXT_SIZE)
    body = build_body(history, current_parts, system_text, use_tools)

    if not await fetch_api_keys():
        msg = "Could not fetch API keys. Please try again later."
        save_message(chat_id, "model", msg)
        await send_message(chat_id, msg)
        return

    content, err = await try_api_call(json.dumps(body))
    if content:
        ai_text, sources = extract_ai_text(content)
        save_message(chat_id, "model", ai_text)
        if ai_text not in ("No response received from AI.", "Failed to parse AI response."):
            formatted = format_response_with_sources(ai_text, sources)
            await send_message(chat_id, formatted, parse_mode="HTML")
        else:
            await send_message(chat_id, ai_text)
    else:
        error = f"Error: {err or 'Unknown error occurred'}"
        save_message(chat_id, "model", error)
        await send_message(chat_id, error)


def parse_agent_response(response: str) -> tuple[str, dict]:
    cleaned = re.sub(r"```python\s*", "", response)
    cleaned = re.sub(r"```\s*", "", cleaned).strip()

    if (m := re.search(r"sendYouTube\(\s*[\"'](.+?)[\"']\s*,\s*[\"'](.+?)[\"']\s*\)", cleaned)):
        return "youtube", {"prompt": m.group(1), "url": m.group(2)}
    if (m := re.search(r"sendYouTube\(\s*(.+?)\s*,\s*[\"'](.+?)[\"']\s*\)", cleaned)):
        return "youtube", {"prompt": m.group(1).strip("\"'"), "url": m.group(2)}
    if (m := re.search(r"sendYouTube\(\s*[\"'](.+?)[\"']\s*,\s*(.+?)\s*\)", cleaned)):
        return "youtube", {"prompt": m.group(1), "url": m.group(2).strip("\"'")}
    if re.search(r"generateImage\s*\(", cleaned):
        return "image", {}
    if re.search(r"sendNormalMessage\s*\(", cleaned):
        return "normal", {}
    return "normal", {}


async def agent_route(chat_id: int, user_text: str, name: str) -> None:
    agent_system = "You are a function router. Only output a single python function call. No explanation."
    prompt = AGENT_PROMPT.format(user_prompt=user_text)
    agent_response = await call_gemini_raw([{"text": prompt}], agent_system)

    if not agent_response:
        await execute_normal_message(chat_id, user_text, name)
        return

    action, params = parse_agent_response(agent_response)

    match action:
        case "youtube":
            await execute_youtube(chat_id, params.get("prompt", "Analyze this video"), params.get("url", ""), name)
        case "image":
            await execute_image(chat_id, user_text, name)
        case _:
            await execute_normal_message(chat_id, user_text, name)


async def execute_normal_message(chat_id: int, query: str, name: str) -> None:
    save_message(chat_id, "user", query)
    current_parts = [{"text": query}]

    stored_image = image_store.get(str(chat_id))
    if stored_image:
        current_parts.append({"inlineData": {"mimeType": "image/jpeg", "data": stored_image}})

    await handle_gemini(chat_id, current_parts, get_system_text(name), use_tools=stored_image is None)


async def execute_youtube(chat_id: int, prompt: str, url: str, name: str) -> None:
    await send_message(chat_id, "🎬 Processing video...", reply_markup=inline_keyboard([[{"text": "⏳ Please wait...", "callback_data": "noop"}]]))

    save_message(chat_id, "user", f"{prompt} [YouTube: {url}]")
    current_parts = [
        {"text": prompt},
        {"fileData": {"mimeType": "video/mp4", "fileUri": url}},
    ]
    await handle_gemini(chat_id, current_parts, get_system_text(name), use_tools=False)


async def execute_image(chat_id: int, query: str, name: str) -> None:
    await send_message(chat_id, "🎨 Generating image...", reply_markup=inline_keyboard([[{"text": "⏳ Creating...", "callback_data": "noop"}]]))

    encoded_prompt = urllib.parse.quote(query)
    image_api_url = f"https://yabes-api.pages.dev/api/ai/image/dalle?prompt={encoded_prompt}"

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(image_api_url)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success") and "output" in data:
                    await send_photo(chat_id, data["output"], f"🎨 {query}")
                    save_message(chat_id, "user", f"Generate image: {query}")
                    save_message(chat_id, "model", f"Generated image for: {query}")
                    await send_message(
                        chat_id, "🎨 Image generated!",
                        reply_markup=inline_keyboard([[{"text": "🔄 Regenerate", "callback_data": f"regen_img:{query[:60]}"}]])
                    )
                    return
        await send_message(chat_id, "❌ Image generation failed. Please try again.")
    except Exception as e:
        await send_message(chat_id, f"❌ Image generation error: {e}")


def inline_keyboard(rows: list[list[dict]]) -> dict:
    return {"inline_keyboard": rows}


def main_menu_keyboard() -> dict:
    return inline_keyboard([
        [{"text": "📜 History", "callback_data": "history"}, {"text": "🗑️ Clear Chat", "callback_data": "clear"}],
        [{"text": "🧹 Clear Image", "callback_data": "cls"}, {"text": "💬 Feedback", "callback_data": "feedback_prompt"}],
        [{"text": "🚪 Exit", "callback_data": "exit_confirm"}],
    ])


def confirm_exit_keyboard() -> dict:
    return inline_keyboard([
        [{"text": "✅ Yes, Exit", "callback_data": "exit_yes"}, {"text": "❌ Cancel", "callback_data": "exit_no"}],
    ])


def confirm_clear_keyboard() -> dict:
    return inline_keyboard([
        [{"text": "✅ Yes, Clear", "callback_data": "clear_yes"}, {"text": "❌ Cancel", "callback_data": "clear_no"}],
    ])


def admin_reply_keyboard(user_id: int) -> dict:
    return inline_keyboard([
        [{"text": "↩️ Reply to Admin", "callback_data": f"reply_admin:{user_id}"}],
    ])


def admin_user_reply_keyboard(target_id: int) -> dict:
    return inline_keyboard([
        [{"text": f"↩️ Reply to {target_id}", "callback_data": f"reply_user:{target_id}"}],
    ])


async def answer_callback(callback_query_id: str, text: str = "") -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(f"{TELEGRAM_API}/answerCallbackQuery", json={"callback_query_id": callback_query_id, "text": text})


async def edit_message(chat_id: int, message_id: int, text: str, parse_mode: Optional[str] = None) -> None:
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(f"{TELEGRAM_API}/editMessageText", json=payload)


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
            chat_id = cb["message"]["chat"]["id"]
            message_id = cb["message"]["message_id"]
            name = get_user_name(cb)

            match cb_data:
                case "noop":
                    await answer_callback(cb_id, "Processing...")

                case "history":
                    await answer_callback(cb_id)
                    history = get_all_history(chat_id)
                    if not history:
                        await send_message(chat_id, "📜 No conversation history found.")
                    else:
                        await send_message(chat_id, f"📜 <b>Conversation History ({len(history)} messages):</b>", parse_mode="HTML")
                        for msg in history:
                            label = "👤 You" if msg["role"] == "user" else "🤖 Mero AI"
                            t = msg.get("text", "")[:3000]
                            await send_message(chat_id, f"<b>{label}:</b>\n{escape_html(t)}", parse_mode="HTML")

                case "clear":
                    await answer_callback(cb_id)
                    await send_message(chat_id, "⚠️ Are you sure you want to clear your chat history?", reply_markup=confirm_clear_keyboard())

                case "clear_yes":
                    await answer_callback(cb_id, "Chat cleared!")
                    clear_history(chat_id)
                    await edit_message(chat_id, message_id, "🗑️ Conversation cleared.", parse_mode="HTML")

                case "clear_no":
                    await answer_callback(cb_id, "Cancelled")
                    await edit_message(chat_id, message_id, "✅ Clear cancelled.")

                case "cls":
                    await answer_callback(cb_id, "Image cleared!")
                    image_store.pop(str(chat_id), None)
                    await send_message(chat_id, "🧹 Stored image cleared.")

                case "feedback_prompt":
                    await answer_callback(cb_id)
                    set_reply_state(chat_id, -1)
                    await send_message(chat_id, "💬 Please type your feedback now:", reply_markup=inline_keyboard([[{"text": "❌ Cancel", "callback_data": "cancel_reply"}]]))

                case "exit_confirm":
                    await answer_callback(cb_id)
                    await send_message(chat_id, "⚠️ Are you sure you want to exit and delete all your data?", reply_markup=confirm_exit_keyboard())

                case "exit_yes":
                    await answer_callback(cb_id, "Goodbye!")
                    remove_user(chat_id)
                    await edit_message(chat_id, message_id, "🚪 You have exited. Send /start anytime to come back.")

                case "exit_no":
                    await answer_callback(cb_id, "Cancelled")
                    await edit_message(chat_id, message_id, "✅ Exit cancelled. You're still here!")

                case "cancel_reply":
                    await answer_callback(cb_id, "Cancelled")
                    clear_reply_state(chat_id)
                    await edit_message(chat_id, message_id, "✅ Cancelled.")

                case _ if cb_data.startswith("reply_admin:"):
                    await answer_callback(cb_id)
                    set_reply_state(chat_id, ADMIN_ID)
                    await send_message(chat_id, "✍️ Type your reply to the admin now:", reply_markup=inline_keyboard([[{"text": "❌ Cancel", "callback_data": "cancel_reply"}]]))

                case _ if cb_data.startswith("reply_user:"):
                    target = int(cb_data.split(":")[1])
                    await answer_callback(cb_id)
                    set_reply_state(chat_id, target)
                    await send_message(chat_id, f"✍️ Type your reply to user <code>{target}</code>:", parse_mode="HTML", reply_markup=inline_keyboard([[{"text": "❌ Cancel", "callback_data": "cancel_reply"}]]))

                case _ if cb_data.startswith("regen_img:"):
                    prompt = cb_data.split(":", 1)[1]
                    await answer_callback(cb_id, "Regenerating...")
                    ensure_user(chat_id, name)
                    await execute_image(chat_id, prompt, name)

            return JSONResponse({"ok": True})

        if "message" not in data:
            return JSONResponse({"ok": True})

        message = data["message"]
        chat_id = message["chat"]["id"]
        name = get_user_name(message)

        reply_target = get_reply_state(chat_id)
        if reply_target is not None and "text" in message:
            clear_reply_state(chat_id)
            reply_text = message["text"].strip()

            if reply_target == -1:
                feedback_msg = (
                    f"📬 <b>New Feedback</b>\n\n"
                    f"👤 <b>From:</b> {escape_html(name)}\n"
                    f"🆔 <b>ID:</b> <code>{chat_id}</code>\n\n"
                    f"💬 {escape_html(reply_text)}"
                )
                result = await send_message(ADMIN_ID, feedback_msg, parse_mode="HTML", reply_markup=admin_user_reply_keyboard(chat_id))
                if result and result.get("ok"):
                    await send_message(chat_id, "✅ Feedback sent to admin!", reply_markup=main_menu_keyboard())
                else:
                    await send_message(chat_id, "❌ Failed to send feedback.")
                return JSONResponse({"ok": True})

            if chat_id == ADMIN_ID:
                admin_msg = f"📩 <b>Message from Admin:</b>\n\n{escape_html(reply_text)}"
                result = await send_message(reply_target, admin_msg, parse_mode="HTML", reply_markup=admin_reply_keyboard(reply_target))
                status = "✅ Sent" if result and result.get("ok") else "❌ Failed"
                await send_message(chat_id, f"{status} to <code>{reply_target}</code>.", parse_mode="HTML")
            else:
                user_msg = (
                    f"📩 <b>Reply from User</b>\n\n"
                    f"👤 {escape_html(name)}\n"
                    f"🆔 <code>{chat_id}</code>\n\n"
                    f"💬 {escape_html(reply_text)}"
                )
                result = await send_message(ADMIN_ID, user_msg, parse_mode="HTML", reply_markup=admin_user_reply_keyboard(chat_id))
                status = "✅ Reply sent" if result and result.get("ok") else "❌ Failed to send reply"
                await send_message(chat_id, status)
            return JSONResponse({"ok": True})

        if any(message.get(t) for t in ("video", "video_note", "document", "audio", "animation", "sticker")):
            await send_message(chat_id, "⚠️ This attachment type is not supported. You can send images or voice messages.", reply_markup=main_menu_keyboard())
            return JSONResponse({"ok": True})

        if message.get("photo"):
            ensure_user(chat_id, name)
            best_photo = message["photo"][-1]
            caption = message.get("caption", "").strip() or "Describe this image in detail."

            await send_message(chat_id, "🖼️ Analyzing image...")

            image_data = await download_telegram_file(best_photo["file_id"])
            if not image_data:
                await send_message(chat_id, "Failed to download the image.")
                return JSONResponse({"ok": True})

            encoded = base64.b64encode(image_data).decode("utf-8")
            image_store[str(chat_id)] = encoded
            save_message(chat_id, "user", f"[Image] {caption}")

            parts = [
                {"text": caption},
                {"inlineData": {"mimeType": "image/jpeg", "data": encoded}},
            ]
            await handle_gemini(chat_id, parts, get_system_text(name), use_tools=False)
            return JSONResponse({"ok": True})

        if message.get("voice"):
            ensure_user(chat_id, name)
            voice = message["voice"]

            if voice.get("duration", 0) > 300:
                await send_message(chat_id, "⚠️ Voice messages can be up to 5 minutes.")
                return JSONResponse({"ok": True})

            await send_message(chat_id, "🎙️ Processing voice message...")

            voice_data = await download_telegram_file(voice["file_id"])
            if not voice_data:
                await send_message(chat_id, "Failed to download the voice message.")
                return JSONResponse({"ok": True})

            encoded_voice = base64.b64encode(voice_data).decode("utf-8")
            mime_type = voice.get("mime_type", "audio/ogg")

            transcription_prompt = "Transcribe the following voice in the original language. Don't write anything else except transcription."
            transcription = await call_gemini_raw(
                [{"text": transcription_prompt}, {"inlineData": {"mimeType": mime_type, "data": encoded_voice}}],
                "You are a transcription engine. Output only the transcription."
            )

            if not transcription:
                await send_message(chat_id, "Failed to transcribe voice message.")
                return JSONResponse({"ok": True})

            save_message(chat_id, "user", f"[Voice] {transcription}")
            await execute_normal_message(chat_id, transcription, name)
            return JSONResponse({"ok": True})

        if "text" not in message:
            return JSONResponse({"ok": True})

        text = message["text"]

        if text == "/start":
            if user_exists(chat_id):
                await send_message(
                    chat_id,
                    "👋 You're already using this bot! Type anything to chat.",
                    parse_mode="HTML",
                    reply_markup=main_menu_keyboard(),
                )
                return JSONResponse({"ok": True})

            save_user(chat_id, name)
            clear_history(chat_id)
            welcome = (
                "✨ <b>Welcome to Mero AI Assistant!</b> ✨\n\n"
                f"Hello, <b>{escape_html(name)}</b>! 🎉\n\n"
                "Your intelligent companion powered by <b>Gemini</b> ⚡\n\n"
                "<b>What I can do:</b>\n\n"
                "💬 <b>Chat</b> — Just type anything\n"
                "🖼️ <b>Image Analysis</b> — Send an image\n"
                "🎙️ <b>Voice Messages</b> — Send voice (up to 5 min)\n"
                "🎬 <b>YouTube Analysis</b> — Send a YouTube link\n"
                "🎨 <b>Image Generation</b> — Ask me to generate an image\n"
                "🌐 <b>Web Search</b> — Automatic when needed\n"
                "🔗 <b>URL Browsing</b> — Send any URL\n"
                "📝 <b>Code</b> — Ask me to write code\n"
                "🌍 <b>Translation</b> — Translate between languages\n"
                "📊 <b>Math &amp; Science</b> — Solve problems\n"
                "📖 <b>Summarization</b> — Summarize text\n\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                f"I remember your last {MAX_HISTORY} conversations.\n\n"
                "🚀 <i>Developed by Sujan Rai</i>"
            )
            await send_message(chat_id, welcome, parse_mode="HTML", reply_markup=main_menu_keyboard())
            return JSONResponse({"ok": True})

        if text == "/menu":
            ensure_user(chat_id, name)
            await send_message(chat_id, "📋 <b>Menu:</b>", parse_mode="HTML", reply_markup=main_menu_keyboard())
            return JSONResponse({"ok": True})

        if text == "/clear":
            ensure_user(chat_id, name)
            clear_history(chat_id)
            await send_message(chat_id, "🗑️ Conversation cleared.", reply_markup=main_menu_keyboard())
            return JSONResponse({"ok": True})

        if text == "/exit":
            if not user_exists(chat_id):
                await send_message(chat_id, "You are not registered. Send /start first.")
                return JSONResponse({"ok": True})
            await send_message(chat_id, "⚠️ Are you sure?", reply_markup=confirm_exit_keyboard())
            return JSONResponse({"ok": True})

        if text == "/history":
            ensure_user(chat_id, name)
            history = get_all_history(chat_id)
            if not history:
                await send_message(chat_id, "📜 No conversation history found.", reply_markup=main_menu_keyboard())
                return JSONResponse({"ok": True})
            await send_message(chat_id, f"📜 <b>History ({len(history)} messages):</b>", parse_mode="HTML")
            for msg in history:
                label = "👤 You" if msg["role"] == "user" else "🤖 Mero AI"
                t = msg.get("text", "")[:3000]
                await send_message(chat_id, f"<b>{label}:</b>\n{escape_html(t)}", parse_mode="HTML")
            return JSONResponse({"ok": True})

        if text == "/total":
            if chat_id != ADMIN_ID:
                await send_message(chat_id, "The command was not recognized.")
                return JSONResponse({"ok": True})
            users = get_all_users()
            response_text = f"📊 <b>Total Users: {len(users)}</b>\n\n"
            response_text += "".join(f"🆔 <code>{uid}</code> — {escape_html(uname)}\n" for uid, uname in users.items()) or "No users registered yet."
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
            target_id_str, msg_content = content.split(" - ", 1)
            target_id_str = target_id_str.strip()
            if not target_id_str.lstrip("-").isdigit():
                await send_message(chat_id, "Invalid user ID.")
                return JSONResponse({"ok": True})
            target_id = int(target_id_str)
            if not user_exists(target_id):
                await send_message(chat_id, f"User <code>{target_id}</code> not found.", parse_mode="HTML")
                return JSONResponse({"ok": True})
            admin_msg = f"📩 <b>Message from Admin:</b>\n\n{escape_html(msg_content.strip())}"
            result = await send_message(target_id, admin_msg, parse_mode="HTML", reply_markup=admin_reply_keyboard(target_id))
            status = "✅ Sent" if result and result.get("ok") else "❌ Failed"
            await send_message(chat_id, f"{status} to <code>{target_id}</code>.", parse_mode="HTML")
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
            success, fail = 0, 0
            for uid in users:
                try:
                    result = await send_message(int(uid), f"📢 <b>Broadcast:</b>\n\n{escape_html(broadcast_msg)}", parse_mode="HTML")
                    (success := success + 1) if result and result.get("ok") else (fail := fail + 1)
                except Exception:
                    fail += 1
            await send_message(chat_id, f"📢 Done.\n✅ Sent: {success}\n❌ Failed: {fail}")
            return JSONResponse({"ok": True})

        if text.startswith("/feedback"):
            ensure_user(chat_id, name)
            feedback_text = text.replace("/feedback", "", 1).strip()
            if not feedback_text:
                set_reply_state(chat_id, -1)
                await send_message(chat_id, "💬 Please type your feedback now:", reply_markup=inline_keyboard([[{"text": "❌ Cancel", "callback_data": "cancel_reply"}]]))
                return JSONResponse({"ok": True})
            feedback_msg = (
                f"📬 <b>New Feedback</b>\n\n"
                f"👤 {escape_html(name)}\n"
                f"🆔 <code>{chat_id}</code>\n\n"
                f"💬 {escape_html(feedback_text)}"
            )
            result = await send_message(ADMIN_ID, feedback_msg, parse_mode="HTML", reply_markup=admin_user_reply_keyboard(chat_id))
            status = "✅ Feedback sent!" if result and result.get("ok") else "❌ Failed to send feedback."
            await send_message(chat_id, status, reply_markup=main_menu_keyboard())
            return JSONResponse({"ok": True})

        if text.startswith("/"):
            await send_message(chat_id, "Command not recognized. Send /start or /menu.", reply_markup=main_menu_keyboard())
            return JSONResponse({"ok": True})

        ensure_user(chat_id, name)

        await send_message(chat_id, "🤖 Thinking...")
        await agent_route(chat_id, text.strip(), name)

        return JSONResponse({"ok": True})

    except Exception:
        return JSONResponse({"ok": True})