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
MODEL = "gemini-2.5-flash-lite"
ADMINS = [7026190306, 6280547580]
TTS_API = "https://tik-tok-tts-s-m-ripon.vercel.app"
DEFAULT_VOICE = "en_us_001"

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


def get_system_text(name: str, chat_id: int) -> str:
    base = (
        f"You're Mero AI assistant developed by Sujan Rai. "
        f"User's name: {name}. "
        f"You can analyze YouTube videos, generate images, answer questions, search the web, "
        f"browse URLs, write code, translate languages, summarize text, solve math problems, "
        f"analyze images, transcribe voice messages, and have natural conversations. "
        f"Always provide helpful, accurate, and well-structured responses. "
        f"You can show emotions. You have emotions. If user sends you voice message, transcribe and reply like a normal."
    )
    custom = r.get(f"settings:{chat_id}:system")
    if custom:
        base += f"\n\nUsers system instructions for you that you must follow: {custom}"
    return base


def history_key(cid: int) -> str:
    return f"chat:{cid}:history"


def reply_state_key(cid: int) -> str:
    return f"chat:{cid}:reply_state"


def state_key(cid: int) -> str:
    return f"chat:{cid}:state"


def is_admin(uid: int) -> bool:
    return uid in ADMINS


def save_user(uid: int, name: str) -> None:
    r.hset("totalUsers", str(uid), name)


def user_exists(uid: int) -> bool:
    return r.hexists("totalUsers", str(uid))


def remove_user_data(uid: int) -> None:
    r.delete(history_key(uid))
    r.delete(reply_state_key(uid))
    r.delete(state_key(uid))
    r.delete(f"settings:{uid}:system")
    r.delete(f"settings:{uid}:voice")
    image_store.pop(str(uid), None)


def get_all_users() -> dict[str, str]:
    return r.hgetall("totalUsers")


def ban_user(uid: int, name: str) -> None:
    r.hset("bannedUsers", str(uid), name)


def unban_user(uid: int) -> None:
    r.hdel("bannedUsers", str(uid))


def is_banned(uid: int) -> bool:
    return r.hexists("bannedUsers", str(uid))


def get_banned_users() -> dict[str, str]:
    return r.hgetall("bannedUsers")


def save_message(cid: int, role: str, text: str) -> None:
    key = history_key(cid)
    if r.llen(key) >= MAX_HISTORY * 2:
        r.ltrim(key, -((MAX_HISTORY - 1) * 2), -1)
    r.rpush(key, json.dumps({"role": role, "text": text}))


def get_all_history(cid: int) -> list[dict]:
    return [json.loads(i) for i in r.lrange(history_key(cid), 0, -1)]


def get_recent_history(cid: int, count: int = CONTEXT_SIZE) -> list[dict]:
    key = history_key(cid)
    total = r.llen(key)
    if total == 0:
        return []
    start = max(0, total - count * 2)
    return [json.loads(i) for i in r.lrange(key, start, -1)]


def clear_history(cid: int) -> None:
    r.delete(history_key(cid))


def set_reply_state(cid: int, target: int) -> None:
    r.set(reply_state_key(cid), str(target), ex=3600)


def get_reply_state(cid: int) -> Optional[int]:
    val = r.get(reply_state_key(cid))
    return int(val) if val else None


def clear_reply_state(cid: int) -> None:
    r.delete(reply_state_key(cid))


def set_state(cid: int, st: str) -> None:
    r.set(state_key(cid), st, ex=3600)


def get_state(cid: int) -> Optional[str]:
    return r.get(state_key(cid))


def clear_state(cid: int) -> None:
    r.delete(state_key(cid))


def get_user_voice(cid: int) -> str:
    return r.get(f"settings:{cid}:voice") or DEFAULT_VOICE


def set_user_voice(cid: int, voice: str) -> None:
    r.set(f"settings:{cid}:voice", voice)


def get_user_system(cid: int) -> str:
    return r.get(f"settings:{cid}:system") or ""


def set_user_system(cid: int, text: str) -> None:
    r.set(f"settings:{cid}:system", text)


def clear_user_system(cid: int) -> None:
    r.delete(f"settings:{cid}:system")


def ensure_user(cid: int, name: str) -> None:
    if not user_exists(cid):
        save_user(cid, name)


def escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def markdown_to_html(text: str) -> str:
    lines = text.split("\n")
    result, code_lines = [], []
    in_code, code_lang = False, ""
    for line in lines:
        if not in_code and (m := re.match(r"^```(\w*)", line)):
            in_code, code_lang, code_lines = True, m.group(1), []
            continue
        if in_code and line.strip() == "```":
            in_code = False
            result.append(f"<pre>{escape_html(chr(10).join(code_lines))}</pre>")
            continue
        if in_code:
            code_lines.append(line)
            continue
        p = escape_html(line)
        for pat, repl in [
            (r"`([^`]+)`", r"<code>\1</code>"),
            (r"\*\*\*(.+?)\*\*\*", r"<b><i>\1</i></b>"),
            (r"\*\*(.+?)\*\*", r"<b>\1</b>"),
            (r"(?<!\*)\*([^*]+?)\*(?!\*)", r"<i>\1</i>"),
            (r"__(.+?)__", r"<u>\1</u>"),
            (r"~~(.+?)~~", r"<s>\1</s>"),
            (r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>'),
        ]:
            p = re.sub(pat, repl, p)
        result.append(p)
    if in_code:
        result.append(f"<pre>{escape_html(chr(10).join(code_lines))}</pre>")
    return "\n".join(result)


async def send_message(cid: int, text: str, parse_mode: Optional[str] = None, reply_markup: Optional[dict] = None) -> Optional[dict]:
    chunks = [text[i:i + 4096] for i in range(0, len(text), 4096)]
    result = None
    async with httpx.AsyncClient(timeout=30.0) as client:
        for chunk in chunks:
            payload = {"chat_id": cid, "text": chunk}
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


async def send_photo(cid: int, photo_url: str, caption: Optional[str] = None) -> dict:
    payload = {"chat_id": cid, "photo": photo_url}
    if caption:
        payload["caption"] = caption
    async with httpx.AsyncClient(timeout=60.0) as client:
        return (await client.post(f"{TELEGRAM_API}/sendPhoto", json=payload)).json()


async def send_voice(cid: int, voice_url: str, caption: Optional[str] = None) -> dict:
    payload = {"chat_id": cid, "voice": voice_url}
    if caption:
        payload["caption"] = caption[:1024]
    async with httpx.AsyncClient(timeout=60.0) as client:
        return (await client.post(f"{TELEGRAM_API}/sendVoice", json=payload)).json()


async def send_voice_bytes(cid: int, audio_bytes: bytes, caption: Optional[str] = None) -> dict:
    async with httpx.AsyncClient(timeout=60.0) as client:
        files = {"voice": ("response.mp3", audio_bytes, "audio/mpeg")}
        data = {"chat_id": str(cid)}
        if caption:
            data["caption"] = caption[:1024]
        return (await client.post(f"{TELEGRAM_API}/sendVoice", files=files, data=data)).json()


async def download_telegram_file(file_id: str) -> Optional[bytes]:
    async with httpx.AsyncClient(timeout=60.0) as client:
        info = (await client.get(f"{TELEGRAM_API}/getFile?file_id={file_id}")).json()
        if not info.get("ok"):
            return None
        resp = await client.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{info['result']['file_path']}")
        return resp.content if resp.status_code == 200 else None


async def generate_tts(text: str, voice: str = DEFAULT_VOICE) -> Optional[bytes]:
    encoded = urllib.parse.quote(text[:300])
    url = f"{TTS_API}/tts?voice={voice}&text={encoded}"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200 and len(resp.content) > 100:
                return resp.content
    except Exception:
        pass
    return None


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


async def handle_gemini(cid: int, current_parts: list[dict], system_text: str, use_tools: bool = True) -> Optional[str]:
    history = get_recent_history(cid, CONTEXT_SIZE)
    body = build_body(history, current_parts, system_text, use_tools)
    if not await fetch_api_keys():
        msg = "Could not fetch API keys. Please try again later."
        save_message(cid, "model", msg)
        await send_message(cid, msg)
        return None
    content, err = await try_api_call(json.dumps(body))
    if content:
        ai_text, sources = extract_ai_text(content)
        save_message(cid, "model", ai_text)
        if ai_text not in ("No response received from AI.", "Failed to parse AI response."):
            formatted = format_response_with_sources(ai_text, sources)
            await send_message(cid, formatted, parse_mode="HTML")
        else:
            await send_message(cid, ai_text)
        return ai_text
    else:
        error = f"Error: {err or 'Unknown error occurred'}"
        save_message(cid, "model", error)
        await send_message(cid, error)
        return None


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


async def agent_route(cid: int, user_text: str, name: str) -> None:
    agent_system = "You are a function router. Only output a single python function call. No explanation."
    prompt = AGENT_PROMPT.format(user_prompt=user_text)
    agent_response = await call_gemini_raw([{"text": prompt}], agent_system)
    if not agent_response:
        await execute_normal_message(cid, user_text, name)
        return
    action, params = parse_agent_response(agent_response)
    match action:
        case "youtube":
            await execute_youtube(cid, params.get("prompt", "Analyze this video"), params.get("url", ""), name)
        case "image":
            await execute_image(cid, user_text, name)
        case _:
            await execute_normal_message(cid, user_text, name)


async def execute_normal_message(cid: int, query: str, name: str) -> None:
    save_message(cid, "user", query)
    current_parts = [{"text": query}]
    stored_image = image_store.get(str(cid))
    if stored_image:
        current_parts.append({"inlineData": {"mimeType": "image/jpeg", "data": stored_image}})
    await handle_gemini(cid, current_parts, get_system_text(name, cid), use_tools=stored_image is None)


async def execute_youtube(cid: int, prompt: str, url: str, name: str) -> None:
    await send_message(cid, "🎬 Processing video...", reply_markup=ikb([[btn("⏳ Please wait...", "noop")]]))
    save_message(cid, "user", f"{prompt} [YouTube: {url}]")
    current_parts = [
        {"text": prompt},
        {"fileData": {"mimeType": "video/mp4", "fileUri": url}},
    ]
    await handle_gemini(cid, current_parts, get_system_text(name, cid), use_tools=False)


async def execute_image(cid: int, query: str, name: str) -> None:
    await send_message(cid, "🎨 Generating image...", reply_markup=ikb([[btn("⏳ Creating...", "noop")]]))
    encoded_prompt = urllib.parse.quote(query)
    image_api_url = f"https://yabes-api.pages.dev/api/ai/image/dalle?prompt={encoded_prompt}"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(image_api_url)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success") and "output" in data:
                    await send_photo(cid, data["output"], f"🎨 {query}")
                    save_message(cid, "user", f"Generate image: {query}")
                    save_message(cid, "model", f"Generated image for: {query}")
                    await send_message(cid, "🎨 Image generated!", reply_markup=ikb([[btn("🔄 Regenerate", f"regen_img:{query[:60]}")]]))
                    return
        await send_message(cid, "❌ Image generation failed. Please try again.")
    except Exception as e:
        await send_message(cid, f"❌ Image generation error: {e}")


def btn(text: str, callback_data: str) -> dict:
    return {"text": text, "callback_data": callback_data}


def ikb(rows: list[list[dict]]) -> dict:
    return {"inline_keyboard": rows}


def user_settings_keyboard() -> dict:
    return ikb([
        [btn("🧠 System Instructions", "set_system"), btn("🎙️ TTS Voice", "set_voice")],
        [btn("🗑️ Clear Chat", "clear"), btn("🧹 Clear Image", "cls")],
        [btn("💬 Feedback", "feedback_prompt"), btn("📜 History", "history")],
        [btn("❌ Close", "close_settings")],
    ])


def admin_settings_keyboard() -> dict:
    return ikb([
        [btn("🧠 System Instructions", "set_system"), btn("🎙️ TTS Voice", "set_voice")],
        [btn("🗑️ Clear Chat", "clear"), btn("🧹 Clear Image", "cls")],
        [btn("📊 Total Users", "admin_total"), btn("🚫 Banned Users", "admin_banned")],
        [btn("📢 Broadcast", "admin_broadcast"), btn("💬 Feedback", "feedback_prompt")],
        [btn("📜 History", "history"), btn("❌ Close", "close_settings")],
    ])


def voice_keyboard() -> dict:
    return ikb([
        [btn("🇺🇸 US Female 1", "voice:en_us_001"), btn("🇺🇸 US Male 1", "voice:en_us_006")],
        [btn("🇺🇸 US Female 2", "voice:en_us_002"), btn("🇺🇸 US Male 2", "voice:en_us_007")],
        [btn("🇺🇸 US Male 3", "voice:en_us_009"), btn("🇺🇸 US Male 4", "voice:en_us_010")],
        [btn("🇬🇧 UK Male 1", "voice:en_uk_001"), btn("🇬🇧 UK Male 2", "voice:en_uk_003")],
        [btn("🇦🇺 AU Female", "voice:en_au_001"), btn("🇦🇺 AU Male", "voice:en_au_002")],
        [btn("😊 Emotional Female", "voice:en_female_emotional"), btn("🎵 Singing Female", "voice:en_female_ht_f08_wonderful_world")],
        [btn("👻 Ghostface", "voice:en_us_ghostface"), btn("🚀 Rocket", "voice:en_us_rocket")],
        [btn("🤖 C3PO", "voice:en_us_c3po"), btn("🧙 Wizard", "voice:en_male_wizard")],
        [btn("🔙 Back", "back_settings")],
    ])


def admin_reply_keyboard(uid: int) -> dict:
    return ikb([[btn("↩️ Reply", f"reply_admin:{uid}")]])


def admin_user_reply_keyboard(target: int) -> dict:
    return ikb([[btn(f"↩️ Reply to {target}", f"reply_user:{target}")]])


def broadcast_reply_keyboard() -> dict:
    return ikb([[btn("💬 Reply to Admin", "feedback_prompt")]])


async def answer_callback(cb_id: str, text: str = "") -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(f"{TELEGRAM_API}/answerCallbackQuery", json={"callback_query_id": cb_id, "text": text})


async def edit_message(cid: int, mid: int, text: str, parse_mode: Optional[str] = None, reply_markup: Optional[dict] = None) -> None:
    payload = {"chat_id": cid, "message_id": mid, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup:
        payload["reply_markup"] = reply_markup
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(f"{TELEGRAM_API}/editMessageText", json=payload)
        if not resp.json().get("ok") and parse_mode:
            payload.pop("parse_mode", None)
            await client.post(f"{TELEGRAM_API}/editMessageText", json=payload)


async def delete_message(cid: int, mid: int) -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(f"{TELEGRAM_API}/deleteMessage", json={"chat_id": cid, "message_id": mid})


async def send_chat_action(cid: int, action: str = "typing") -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(f"{TELEGRAM_API}/sendChatAction", json={"chat_id": cid, "action": action})


def check_banned(cid: int) -> bool:
    return is_banned(cid) and not is_admin(cid)


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

            if check_banned(cid) and cb_data not in ("request_unban",):
                await answer_callback(cb_id, "You are banned.")
                return JSONResponse({"ok": True})

            if cb_data == "noop":
                await answer_callback(cb_id, "Processing...")
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

            if cb_data == "history":
                await answer_callback(cb_id)
                history = get_all_history(cid)
                if not history:
                    await send_message(cid, "📜 No conversation history found.")
                else:
                    await send_message(cid, f"📜 <b>History ({len(history)} messages):</b>", parse_mode="HTML")
                    for msg in history:
                        label = "👤 You" if msg["role"] == "user" else "🤖 Mero AI"
                        t = msg.get("text", "")[:3000]
                        await send_message(cid, f"<b>{label}:</b>\n{escape_html(t)}", parse_mode="HTML")
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
                await answer_callback(cb_id, "Image cleared!")
                image_store.pop(str(cid), None)
                await send_message(cid, "🧹 Stored image cleared.")
                return JSONResponse({"ok": True})

            if cb_data == "feedback_prompt":
                await answer_callback(cb_id)
                set_reply_state(cid, -1)
                await send_message(cid, "💬 Type your feedback:", reply_markup=ikb([[btn("❌ Cancel", "cancel_reply")]]))
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
                    f"🧠 <b>System Instructions</b>\n\n{info}\n\nType new instructions or send /clear_system to remove:",
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

            if cb_data.startswith("reply_admin:"):
                await answer_callback(cb_id)
                set_reply_state(cid, ADMINS[0])
                await send_message(cid, "✍️ Type your reply to admin:", reply_markup=ikb([[btn("❌ Cancel", "cancel_reply")]]))
                return JSONResponse({"ok": True})

            if cb_data.startswith("reply_user:"):
                target = int(cb_data.split(":")[1])
                await answer_callback(cb_id)
                set_reply_state(cid, target)
                await send_message(cid, f"✍️ Type reply to <code>{target}</code>:", parse_mode="HTML", reply_markup=ikb([[btn("❌ Cancel", "cancel_reply")]]))
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
                for uid_str, uname in users.items():
                    uid_int = int(uid_str)
                    if uid_int not in ADMINS:
                        rows.append([btn(f"🚫 Ban {uname} ({uid_str})", f"ban_confirm:{uid_str}")])
                text = f"📊 <b>Total Users: {len(users)}</b>\n\n"
                text += "".join(f"🆔 <code>{u}</code> — {escape_html(n)}\n" for u, n in users.items())
                rows.append([btn("🔙 Back", "back_settings")])
                await send_message(cid, text, parse_mode="HTML", reply_markup=ikb(rows))
                return JSONResponse({"ok": True})

            if cb_data.startswith("ban_confirm:"):
                if not is_admin(cid):
                    await answer_callback(cb_id, "Unauthorized")
                    return JSONResponse({"ok": True})
                target = cb_data.split(":")[1]
                uname = get_all_users().get(target, "Unknown")
                await answer_callback(cb_id)
                await send_message(
                    cid,
                    f"⚠️ Ban <b>{escape_html(uname)}</b> (<code>{target}</code>)?",
                    parse_mode="HTML",
                    reply_markup=ikb([
                        [btn("✅ Yes, Ban", f"ban_yes:{target}"), btn("❌ Cancel", "back_settings")],
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
                await send_message(cid, "📢 Type your broadcast message:", reply_markup=ikb([[btn("❌ Cancel", "cancel_reply")]]))
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
        if st and "text" in message:
            text = message["text"].strip()

            if st == "awaiting_system_instructions":
                clear_state(cid)
                if text == "/clear_system":
                    clear_user_system(cid)
                    await send_message(cid, "🗑️ System instructions cleared.", reply_markup=ikb([[btn("🔙 Back", "back_settings")]]))
                else:
                    set_user_system(cid, text)
                    await send_message(cid, f"✅ System instructions updated:\n\n<i>{escape_html(text[:500])}</i>", parse_mode="HTML", reply_markup=ikb([[btn("🔙 Back", "back_settings")]]))
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

        reply_target = get_reply_state(cid)
        if reply_target is not None and "text" in message:
            clear_reply_state(cid)
            reply_text = message["text"].strip()

            if reply_target == -1:
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
                admin_msg = f"📩 <b>Message from Admin:</b>\n\n{escape_html(reply_text)}"
                result = await send_message(reply_target, admin_msg, parse_mode="HTML", reply_markup=admin_reply_keyboard(reply_target))
                status = "✅ Sent" if result and result.get("ok") else "❌ Failed"
                await send_message(cid, f"{status} to <code>{reply_target}</code>.", parse_mode="HTML")
            else:
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

        if any(message.get(t) for t in ("video", "video_note", "document", "audio", "animation", "sticker")):
            await send_message(cid, "⚠️ This attachment type is not supported. Send images or voice messages.")
            return JSONResponse({"ok": True})

        if message.get("photo"):
            ensure_user(cid, name)
            best_photo = message["photo"][-1]
            caption = message.get("caption", "").strip() or "Describe this image in detail."
            await send_chat_action(cid, "typing")
            await send_message(cid, "🖼️ Analyzing image...")
            image_data = await download_telegram_file(best_photo["file_id"])
            if not image_data:
                await send_message(cid, "Failed to download the image.")
                return JSONResponse({"ok": True})
            encoded = base64.b64encode(image_data).decode("utf-8")
            image_store[str(cid)] = encoded
            save_message(cid, "user", f"[Image] {caption}")
            parts = [
                {"text": caption},
                {"inlineData": {"mimeType": "image/jpeg", "data": encoded}},
            ]
            await handle_gemini(cid, parts, get_system_text(name, cid), use_tools=False)
            return JSONResponse({"ok": True})

        if message.get("voice"):
            ensure_user(cid, name)
            voice = message["voice"]
            if voice.get("duration", 0) > 300:
                await send_message(cid, "⚠️ Voice messages up to 5 minutes only.")
                return JSONResponse({"ok": True})
            await send_chat_action(cid, "typing")
            await send_message(cid, "🎙️ Processing voice...")
            voice_data = await download_telegram_file(voice["file_id"])
            if not voice_data:
                await send_message(cid, "Failed to download voice message.")
                return JSONResponse({"ok": True})
            encoded_voice = base64.b64encode(voice_data).decode("utf-8")
            mime_type = voice.get("mime_type", "audio/ogg")
            transcription = await call_gemini_raw(
                [{"text": "Transcribe the following voice in the original language. Don't write anything else except transcription."}, {"inlineData": {"mimeType": mime_type, "data": encoded_voice}}],
                "You are a transcription engine. Output only the transcription.",
            )
            if not transcription:
                await send_message(cid, "Failed to transcribe voice message.")
                return JSONResponse({"ok": True})
            save_message(cid, "user", f"[Voice] {transcription}")
            current_parts = [{"text": transcription}]
            stored_image = image_store.get(str(cid))
            if stored_image:
                current_parts.append({"inlineData": {"mimeType": "image/jpeg", "data": stored_image}})
            ai_response = await handle_gemini(cid, current_parts, get_system_text(name, cid), use_tools=stored_image is None)
            if ai_response and ai_response not in ("No response received from AI.", "Failed to parse AI response."):
                user_voice = get_user_voice(cid)
                tts_text = ai_response[:300]
                await send_chat_action(cid, "record_voice")
                audio_bytes = await generate_tts(tts_text, user_voice)
                if audio_bytes:
                    await send_voice_bytes(cid, audio_bytes, f"🎙️ Voice response")
            return JSONResponse({"ok": True})

        if "text" not in message:
            return JSONResponse({"ok": True})

        text = message["text"]

        if text == "/start":
            if user_exists(cid):
                kb = admin_settings_keyboard() if is_admin(cid) else user_settings_keyboard()
                await send_message(cid, "👋 Welcome back! Type anything to chat.", parse_mode="HTML", reply_markup=kb)
                return JSONResponse({"ok": True})
            save_user(cid, name)
            clear_history(cid)
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
                "Use /settings to configure the bot.\n\n"
                "🚀 <i>Developed by Sujan Rai</i>"
            )
            kb = admin_settings_keyboard() if is_admin(cid) else user_settings_keyboard()
            await send_message(cid, welcome, parse_mode="HTML", reply_markup=kb)
            return JSONResponse({"ok": True})

        if text == "/settings" or text == "/menu":
            ensure_user(cid, name)
            kb = admin_settings_keyboard() if is_admin(cid) else user_settings_keyboard()
            await send_message(cid, "⚙️ <b>Settings</b>", parse_mode="HTML", reply_markup=kb)
            return JSONResponse({"ok": True})

        if text == "/clear":
            ensure_user(cid, name)
            clear_history(cid)
            await send_message(cid, "🗑️ Conversation cleared.")
            return JSONResponse({"ok": True})

        if text == "/history":
            ensure_user(cid, name)
            history = get_all_history(cid)
            if not history:
                await send_message(cid, "📜 No conversation history.")
                return JSONResponse({"ok": True})
            await send_message(cid, f"📜 <b>History ({len(history)} messages):</b>", parse_mode="HTML")
            for msg in history:
                label = "👤 You" if msg["role"] == "user" else "🤖 Mero AI"
                t = msg.get("text", "")[:3000]
                await send_message(cid, f"<b>{label}:</b>\n{escape_html(t)}", parse_mode="HTML")
            return JSONResponse({"ok": True})

        if text == "/total":
            if not is_admin(cid):
                await send_message(cid, "Command not recognized.")
                return JSONResponse({"ok": True})
            users = get_all_users()
            response_text = f"📊 <b>Total Users: {len(users)}</b>\n\n"
            response_text += "".join(f"🆔 <code>{u}</code> — {escape_html(n)}\n" for u, n in users.items()) or "No users."
            await send_message(cid, response_text, parse_mode="HTML")
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
                await send_message(cid, "💬 Type your feedback:", reply_markup=ikb([[btn("❌ Cancel", "cancel_reply")]]))
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

        if text.startswith("/"):
            await send_message(cid, "Command not recognized. Use /settings or /start.")
            return JSONResponse({"ok": True})

        ensure_user(cid, name)
        await send_chat_action(cid, "typing")
        await send_message(cid, "🤖 Thinking...")
        await agent_route(cid, text.strip(), name)
        return JSONResponse({"ok": True})

    except Exception:
        return JSONResponse({"ok": True})