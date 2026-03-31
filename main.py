from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import httpx
import urllib.parse
import json
import re
import os
import redis
import base64
import asyncio
from typing import Optional

app = FastAPI()

BOT_TOKEN = "8655216165:AAEoDExRbxAmZVxGL9H0na4hziBEv6I-0RA"
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
POOL_API = "https://sr-pool-api-5bm.pages.dev"
MODEL = "gemini-2.5-flash"
ADMINS = [7026190306, 6280547580]
TTS_API = "https://tik-tok-tts-s-m-ripon.vercel.app"
DEFAULT_VOICE = "en_us_001"
GEMINI_FILES_API = "https://generativelanguage.googleapis.com/upload/v1beta/files"
GEMINI_FILES_GET = "https://generativelanguage.googleapis.com/v1beta/files"

REDIS_URL = os.environ.get("REDIS_URL", "")
r = redis.from_url(REDIS_URL, decode_responses=True)

api_keys: list[str] = []

MAX_HISTORY = 30
CONTEXT_SIZE = 30

SHARE_TEXT = "🚀 Check out Mero AI Assistant — your free, fast & powerful AI companion on Telegram!\n\nhttps://t.me/MeroAIBot"

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

TEMPLATE_PROMPTS = [
    "Explain quantum computing simply",
    "Write a Python web scraper",
    "Summarize the latest AI news",
    "Translate 'hello' to 10 languages",
    "Solve: integral of x²·sin(x) dx",
    "Generate a business plan outline",
    "Explain blockchain in 3 sentences",
    "Write a poem about the ocean",
    "Compare React vs Vue vs Angular",
    "Tips for learning a new language",
]

SUPPORTED_MIME_TYPES = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.ms-excel": "xls",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/vnd.ms-powerpoint": "ppt",
    "text/plain": "txt",
    "text/csv": "csv",
    "text/html": "html",
    "text/css": "css",
    "text/javascript": "js",
    "application/json": "json",
    "application/xml": "xml",
    "text/xml": "xml",
    "text/x-python": "py",
    "text/x-java-source": "java",
    "text/x-c": "c",
    "text/x-c++": "cpp",
    "text/x-csharp": "cs",
    "text/x-go": "go",
    "text/x-rust": "rs",
    "text/x-ruby": "rb",
    "text/x-php": "php",
    "text/x-swift": "swift",
    "text/x-kotlin": "kt",
    "text/x-scala": "scala",
    "text/x-shellscript": "sh",
    "text/x-sql": "sql",
    "text/x-yaml": "yaml",
    "text/x-toml": "toml",
    "text/markdown": "md",
    "text/x-typescript": "ts",
    "text/x-lua": "lua",
    "text/x-perl": "pl",
    "text/x-r": "r",
    "text/x-dart": "dart",
    "application/x-httpd-php": "php",
    "application/javascript": "js",
    "application/typescript": "ts",
    "application/x-yaml": "yaml",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/ogg": "ogg",
    "audio/wav": "wav",
    "audio/webm": "webm",
    "audio/x-wav": "wav",
    "audio/flac": "flac",
    "audio/aac": "aac",
    "video/mp4": "mp4",
    "video/webm": "webm",
    "video/quicktime": "mov",
    "video/x-msvideo": "avi",
    "video/x-matroska": "mkv",
    "video/3gpp": "3gp",
}

CODE_EXTENSIONS = {
    "py", "js", "ts", "java", "c", "cpp", "cs", "go", "rs", "rb", "php",
    "swift", "kt", "scala", "sh", "sql", "yaml", "yml", "toml", "md",
    "html", "css", "json", "xml", "lua", "pl", "r", "dart", "jsx", "tsx",
    "vue", "svelte", "zig", "nim", "ex", "exs", "clj", "hs", "ml", "fs",
    "v", "d", "pas", "bas", "asm", "s", "coffee", "elm", "erl", "groovy",
    "tf", "dockerfile", "makefile", "cmake", "gradle", "bat", "ps1",
    "ini", "cfg", "conf", "env", "gitignore", "editorconfig", "txt",
    "csv", "tsv", "log", "diff", "patch",
}


def get_system_text(name: str, chat_id: int) -> str:
    base = (
        f"You're Mero AI assistant developed by Sujan Rai. "
        f"User's name: {name}. "
        f"You can analyze YouTube videos, generate images, answer questions, search the web, "
        f"browse URLs, write code in 100+ languages, translate languages, summarize text, solve math problems, "
        f"analyze images, analyze documents (PDF, DOCX, etc.), analyze audio and video files, "
        f"transcribe voice messages, and have natural conversations. "
        f"Always provide helpful, accurate, and well-structured responses. "
        f"You can show emotions. You have emotions. If user sends you voice message, transcribe and reply naturally. "
        f"Use markdown formatting: **bold**, *italic*, `code`, ```codeblocks```, lists, headers etc. "
        f"When writing code, always specify the language in code blocks like ```python. "
        f"Be concise but thorough. Use bullet points and structured formatting when appropriate."
    )
    custom = r.get(f"settings:{chat_id}:system")
    if custom:
        base += f"\n\nIMPORTANT - User's custom system instructions that you MUST follow strictly:\n{custom}"
    return base


def hk(cid: int) -> str:
    return f"chat:{cid}:history"


def rsk(cid: int) -> str:
    return f"chat:{cid}:reply_state"


def sk(cid: int) -> str:
    return f"chat:{cid}:state"


def fk(cid: int) -> str:
    return f"chat:{cid}:file"


def is_admin(uid: int) -> bool:
    return uid in ADMINS


def save_user(uid: int, name: str) -> None:
    r.hset("totalUsers", str(uid), name)


def user_exists(uid: int) -> bool:
    return r.hexists("totalUsers", str(uid))


def remove_all_user_data(uid: int) -> None:
    r.delete(hk(uid), rsk(uid), sk(uid), fk(uid))
    r.delete(f"settings:{uid}:system", f"settings:{uid}:voice")
    r.hdel("totalUsers", str(uid))


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
    key = hk(cid)
    if r.llen(key) >= MAX_HISTORY * 2:
        r.ltrim(key, -((MAX_HISTORY - 1) * 2), -1)
    r.rpush(key, json.dumps({"role": role, "text": text}))


def get_all_history(cid: int) -> list[dict]:
    return [json.loads(i) for i in r.lrange(hk(cid), 0, -1)]


def get_recent_history(cid: int, count: int = CONTEXT_SIZE) -> list[dict]:
    key = hk(cid)
    total = r.llen(key)
    if total == 0:
        return []
    start = max(0, total - count * 2)
    return [json.loads(i) for i in r.lrange(key, start, -1)]


def clear_history(cid: int) -> None:
    r.delete(hk(cid))


def set_reply_state(cid: int, target: int) -> None:
    r.set(rsk(cid), str(target), ex=3600)


def get_reply_state(cid: int) -> Optional[int]:
    val = r.get(rsk(cid))
    return int(val) if val else None


def clear_reply_state(cid: int) -> None:
    r.delete(rsk(cid))


def set_state(cid: int, st: str) -> None:
    r.set(sk(cid), st, ex=3600)


def get_state(cid: int) -> Optional[str]:
    return r.get(sk(cid))


def clear_state(cid: int) -> None:
    r.delete(sk(cid))


def save_file_data(cid: int, data: dict) -> None:
    r.set(fk(cid), json.dumps(data), ex=86400)


def get_file_data(cid: int) -> Optional[dict]:
    val = r.get(fk(cid))
    return json.loads(val) if val else None


def clear_file_data(cid: int) -> None:
    r.delete(fk(cid))


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
    result: list[str] = []
    code_lines: list[str] = []
    in_code = False
    code_lang = ""

    for line in lines:
        if not in_code:
            m = re.match(r"^```(\w*)", line)
            if m:
                in_code = True
                code_lang = m.group(1)
                code_lines = []
                continue
        else:
            if line.strip() == "```":
                in_code = False
                code_content = escape_html("\n".join(code_lines))
                if code_lang:
                    result.append(f"<pre><code class=\"language-{code_lang}\">{code_content}</code></pre>")
                else:
                    result.append(f"<pre>{code_content}</pre>")
                continue
            code_lines.append(line)
            continue

        if re.match(r"^#{1,6}\s+", line):
            m2 = re.match(r"^(#{1,6})\s+(.*)", line)
            if m2:
                level = len(m2.group(1))
                heading_text = m2.group(2)
                p = escape_html(heading_text)
                p = _inline_format(p)
                if level <= 2:
                    result.append(f"<b>{p}</b>")
                else:
                    result.append(f"<b>{p}</b>")
                continue

        p = escape_html(line)
        p = _inline_format(p)
        result.append(p)

    if in_code:
        code_content = escape_html("\n".join(code_lines))
        result.append(f"<pre>{code_content}</pre>")

    return "\n".join(result)


def _inline_format(p: str) -> str:
    p = re.sub(r"`([^`]+)`", r"<code>\1</code>", p)
    p = re.sub(r"\*\*\*(.+?)\*\*\*", r"<b><i>\1</i></b>", p)
    p = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", p)
    p = re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"<i>\1</i>", p)
    p = re.sub(r"__(.+?)__", r"<u>\1</u>", p)
    p = re.sub(r"~~(.+?)~~", r"<s>\1</s>", p)
    p = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', p)
    return p


async def send_message(cid: int, text: str, parse_mode: Optional[str] = None, reply_markup: Optional[dict] = None) -> Optional[dict]:
    chunks = [text[i:i + 4096] for i in range(0, len(text), 4096)]
    result = None
    async with httpx.AsyncClient(timeout=30.0) as client:
        for chunk in chunks:
            payload: dict = {"chat_id": cid, "text": chunk}
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


async def send_photo(cid: int, photo_url: str, caption: Optional[str] = None, reply_markup: Optional[dict] = None) -> dict:
    payload: dict = {"chat_id": cid, "photo": photo_url}
    if caption:
        payload["caption"] = caption[:1024]
    if reply_markup:
        payload["reply_markup"] = reply_markup
    async with httpx.AsyncClient(timeout=60.0) as client:
        return (await client.post(f"{TELEGRAM_API}/sendPhoto", json=payload)).json()


async def send_voice_bytes(cid: int, audio_bytes: bytes, caption: Optional[str] = None) -> dict:
    async with httpx.AsyncClient(timeout=60.0) as client:
        files = {"voice": ("response.mp3", audio_bytes, "audio/mpeg")}
        data: dict = {"chat_id": str(cid)}
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


async def get_telegram_file_info(file_id: str) -> Optional[dict]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        info = (await client.get(f"{TELEGRAM_API}/getFile?file_id={file_id}")).json()
        if info.get("ok"):
            return info["result"]
    return None


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


async def upload_to_gemini_files(file_bytes: bytes, mime_type: str, display_name: str) -> Optional[dict]:
    if not await fetch_api_keys():
        return None
    key = api_keys[0]
    upload_url = f"{GEMINI_FILES_API}?key={key}"
    metadata = json.dumps({"file": {"displayName": display_name}})
    boundary = "----GeminiBoundary7MA4YWxkTrZu0gW"
    body = (
        f"--{boundary}\r\n"
        f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{metadata}\r\n"
        f"--{boundary}\r\n"
        f"Content-Type: {mime_type}\r\n\r\n"
    ).encode("utf-8") + file_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

    headers = {"Content-Type": f"multipart/related; boundary={boundary}"}
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(upload_url, content=body, headers=headers)
            if resp.status_code == 200:
                result = resp.json()
                file_info = result.get("file", {})
                file_uri = file_info.get("uri", "")
                file_name = file_info.get("name", "")
                state = file_info.get("state", "")
                if state == "PROCESSING":
                    for _ in range(30):
                        await asyncio.sleep(2)
                        check_resp = await client.get(f"{GEMINI_FILES_GET}/{file_name}?key={key}")
                        if check_resp.status_code == 200:
                            check_data = check_resp.json()
                            if check_data.get("state") == "ACTIVE":
                                return {"uri": check_data.get("uri", file_uri), "mime_type": check_data.get("mimeType", mime_type), "name": file_name, "display_name": display_name}
                    return None
                return {"uri": file_uri, "mime_type": mime_type, "name": file_name, "display_name": display_name}
    except Exception:
        pass
    return None


def build_body(history_messages: list[dict], current_parts: list, system_text: str, use_tools: bool = True) -> dict:
    contents = []
    for msg in history_messages:
        contents.append({
            "role": "user" if msg["role"] == "user" else "model",
            "parts": [{"text": msg.get("text", "")}]
        })
    contents.append({"role": "user", "parts": current_parts})
    body: dict = {
        "system_instruction": {"parts": [{"text": system_text}]},
        "contents": contents,
        "generationConfig": {"maxOutputTokens": 65536},
    }
    if use_tools:
        body["tools"] = [{"google_search": {}}, {"url_context": {}}]
    return body


def extract_sources(data: dict) -> list[dict]:
    sources: list[dict] = []
    seen: set[str] = set()
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


async def call_gemini_raw(parts: list, system_text: str) -> Optional[str]:
    if not await fetch_api_keys():
        return None
    body = {
        "system_instruction": {"parts": [{"text": system_text}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"maxOutputTokens": 2048},
    }
    content, _ = await try_api_call(json.dumps(body))
    if not content:
        return None
    text, _ = extract_ai_text(content)
    return text


async def handle_gemini(cid: int, current_parts: list, system_text: str, use_tools: bool = True) -> Optional[str]:
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
    current_parts: list = [{"text": query}]
    file_data = get_file_data(cid)
    has_file = False
    if file_data:
        current_parts.append({"fileData": {"mimeType": file_data["mime_type"], "fileUri": file_data["uri"]}})
        has_file = True
    await handle_gemini(cid, current_parts, get_system_text(name, cid), use_tools=not has_file)


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
                    await send_photo(cid, data["output"], f"🎨 {query}", reply_markup=ikb([[btn("🔄 Regenerate", f"regen_img:{query[:60]}")]]))
                    save_message(cid, "user", f"Generate image: {query}")
                    save_message(cid, "model", f"Generated image for: {query}")
                    return
        await send_message(cid, "❌ Image generation failed. Please try again.")
    except Exception as e:
        await send_message(cid, f"❌ Image generation error: {e}")


def btn(text: str, callback_data: str) -> dict:
    return {"text": text, "callback_data": callback_data}


def url_btn(text: str, url: str) -> dict:
    return {"text": text, "url": url}


def switch_btn(text: str, switch_inline_query: str) -> dict:
    return {"text": text, "switch_inline_query": switch_inline_query}


def ikb(rows: list[list[dict]]) -> dict:
    return {"inline_keyboard": rows}


def start_keyboard() -> dict:
    return ikb([
        [btn("⚙️ Settings", "open_settings"), btn("📤 Share Bot", "share_bot")],
    ])


def template_prompts_keyboard() -> dict:
    rows = []
    for i in range(0, len(TEMPLATE_PROMPTS), 2):
        row = [btn(f"💡 {TEMPLATE_PROMPTS[i][:30]}", f"tp:{i}")]
        if i + 1 < len(TEMPLATE_PROMPTS):
            row.append(btn(f"💡 {TEMPLATE_PROMPTS[i+1][:30]}", f"tp:{i+1}"))
        rows.append(row)
    return ikb(rows)


def user_settings_keyboard() -> dict:
    return ikb([
        [btn("🧠 System Instructions", "set_system"), btn("🎙️ TTS Voice", "set_voice")],
        [btn("🗑️ Clear Chat", "clear"), btn("🧹 Clear Attachment", "cls")],
        [btn("💬 Feedback", "feedback_prompt"), btn("📜 History", "history")],
        [btn("🌡️ Temperature", "set_temp"), btn("🔄 Export Chat", "export_chat")],
        [btn("❌ Close", "close_settings")],
    ])


def admin_settings_keyboard() -> dict:
    return ikb([
        [btn("🧠 System Instructions", "set_system"), btn("🎙️ TTS Voice", "set_voice")],
        [btn("🗑️ Clear Chat", "clear"), btn("🧹 Clear Attachment", "cls")],
        [btn("📊 Total Users", "admin_total"), btn("🚫 Banned Users", "admin_banned")],
        [btn("📢 Broadcast", "admin_broadcast"), btn("💬 Feedback", "feedback_prompt")],
        [btn("📜 History", "history"), btn("🔄 Export Chat", "export_chat")],
        [btn("🌡️ Temperature", "set_temp"), btn("❌ Close", "close_settings")],
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


def temp_keyboard() -> dict:
    return ikb([
        [btn("🧊 0.0 Precise", "temp:0.0"), btn("❄️ 0.3 Balanced", "temp:0.3")],
        [btn("🌤️ 0.7 Creative", "temp:0.7"), btn("🔥 1.0 Very Creative", "temp:1.0")],
        [btn("🌋 1.5 Wild", "temp:1.5"), btn("💥 2.0 Maximum", "temp:2.0")],
        [btn("🔙 Back", "back_settings")],
    ])


def photo_keyboard() -> dict:
    return ikb([
        [btn("📝 Describe", "describe_photo")],
        [btn("❌ Cancel", "cancel_attachment")],
    ])


def file_prompt_keyboard() -> dict:
    return ikb([
        [btn("❌ Cancel", "cancel_attachment")],
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
    payload: dict = {"chat_id": cid, "message_id": mid, "text": text}
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


def get_user_temp(cid: int) -> float:
    val = r.get(f"settings:{cid}:temp")
    return float(val) if val else 0.7


def set_user_temp(cid: int, temp: float) -> None:
    r.set(f"settings:{cid}:temp", str(temp))


def detect_mime_type(file_path: str, provided_mime: Optional[str] = None) -> str:
    if provided_mime and provided_mime in SUPPORTED_MIME_TYPES:
        return provided_mime
    ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
    ext_to_mime = {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "doc": "application/msword",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xls": "application/vnd.ms-excel",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "ppt": "application/vnd.ms-powerpoint",
        "txt": "text/plain",
        "csv": "text/csv",
        "html": "text/html",
        "css": "text/css",
        "js": "application/javascript",
        "json": "application/json",
        "xml": "application/xml",
        "py": "text/x-python",
        "java": "text/x-java-source",
        "c": "text/x-c",
        "cpp": "text/x-c++",
        "cs": "text/x-csharp",
        "go": "text/x-go",
        "rs": "text/x-rust",
        "rb": "text/x-ruby",
        "php": "text/x-php",
        "swift": "text/x-swift",
        "kt": "text/x-kotlin",
        "scala": "text/x-scala",
        "sh": "text/x-shellscript",
        "sql": "text/x-sql",
        "yaml": "application/x-yaml",
        "yml": "application/x-yaml",
        "toml": "text/x-toml",
        "md": "text/markdown",
        "ts": "application/typescript",
        "tsx": "application/typescript",
        "jsx": "application/javascript",
        "lua": "text/x-lua",
        "pl": "text/x-perl",
        "r": "text/x-r",
        "dart": "text/x-dart",
        "mp3": "audio/mpeg",
        "m4a": "audio/mp4",
        "ogg": "audio/ogg",
        "wav": "audio/wav",
        "webm": "audio/webm",
        "flac": "audio/flac",
        "aac": "audio/aac",
        "mp4": "video/mp4",
        "mov": "video/quicktime",
        "avi": "video/x-msvideo",
        "mkv": "video/x-matroska",
        "3gp": "video/3gpp",
    }
    if ext in ext_to_mime:
        return ext_to_mime[ext]
    if ext in CODE_EXTENSIONS:
        return "text/plain"
    if provided_mime:
        return provided_mime
    return "application/octet-stream"


def get_display_name(file_path: str, file_name: Optional[str] = None) -> str:
    if file_name:
        return file_name
    if "." in file_path:
        return file_path.rsplit("/", 1)[-1]
    return "uploaded_file"


async def process_attachment(cid: int, file_id: str, mime_type: str, file_name: str) -> Optional[dict]:
    file_bytes = await download_telegram_file(file_id)
    if not file_bytes:
        return None
    result = await upload_to_gemini_files(file_bytes, mime_type, file_name)
    if result:
        save_file_data(cid, result)
        return result
    return None


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
                    reply_markup=ikb([
                        [url_btn("📤 Share Now", f"https://t.me/share/url?url=https://t.me/MeroAIBot&text={urllib.parse.quote(SHARE_TEXT)}")],
                    ]),
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
                file_data = get_file_data(cid)
                if not file_data:
                    await send_message(cid, "❌ No image found. Please send an image first.")
                    return JSONResponse({"ok": True})
                ensure_user(cid, name)
                await send_chat_action(cid, "typing")
                prompt = "Describe this image in detail."
                save_message(cid, "user", f"[Image] {prompt}")
                parts: list = [
                    {"text": prompt},
                    {"fileData": {"mimeType": file_data["mime_type"], "fileUri": file_data["uri"]}},
                ]
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
                async with httpx.AsyncClient(timeout=30.0) as client:
                    files = {"document": ("chat_history.txt", file_bytes, "text/plain")}
                    form_data = {"chat_id": str(cid), "caption": "📜 Your chat history export"}
                    await client.post(f"{TELEGRAM_API}/sendDocument", files=files, data=form_data)
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
                    file_data = get_file_data(cid)
                    if not file_data:
                        await send_message(cid, "❌ File not found. Please upload again.")
                        return JSONResponse({"ok": True})
                    save_message(cid, "user", f"[File: {file_data.get('display_name', 'file')}] {text}")
                    parts: list = [
                        {"text": text},
                        {"fileData": {"mimeType": file_data["mime_type"], "fileUri": file_data["uri"]}},
                    ]
                    await handle_gemini(cid, parts, get_system_text(name, cid), use_tools=False)
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

        if message.get("photo"):
            ensure_user(cid, name)
            best_photo = message["photo"][-1]
            caption = message.get("caption", "").strip()
            await send_chat_action(cid, "typing")
            await send_message(cid, "🖼️ Uploading image...")
            file_info = await get_telegram_file_info(best_photo["file_id"])
            if not file_info:
                await send_message(cid, "❌ Failed to get image info.")
                return JSONResponse({"ok": True})
            file_bytes = await download_telegram_file(best_photo["file_id"])
            if not file_bytes:
                await send_message(cid, "❌ Failed to download image.")
                return JSONResponse({"ok": True})
            file_path = file_info.get("file_path", "photo.jpg")
            display = get_display_name(file_path, "photo.jpg")
            mime = detect_mime_type(file_path, "image/jpeg")
            uploaded = await upload_to_gemini_files(file_bytes, mime, display)
            if not uploaded:
                encoded = base64.b64encode(file_bytes).decode("utf-8")
                save_file_data(cid, {"uri": "", "mime_type": "image/jpeg", "name": "", "display_name": display, "base64": encoded})
                if caption:
                    save_message(cid, "user", f"[Image] {caption}")
                    parts_list: list = [
                        {"text": caption},
                        {"inlineData": {"mimeType": "image/jpeg", "data": encoded}},
                    ]
                    await handle_gemini(cid, parts_list, get_system_text(name, cid), use_tools=False)
                else:
                    await send_message(
                        cid,
                        f"✅ Image uploaded: <b>{escape_html(display)}</b>\n\nType your prompt or tap Describe.",
                        parse_mode="HTML",
                        reply_markup=photo_keyboard(),
                    )
                return JSONResponse({"ok": True})
            if caption:
                save_message(cid, "user", f"[Image: {display}] {caption}")
                parts_list2: list = [
                    {"text": caption},
                    {"fileData": {"mimeType": uploaded["mime_type"], "fileUri": uploaded["uri"]}},
                ]
                await handle_gemini(cid, parts_list2, get_system_text(name, cid), use_tools=False)
            else:
                await send_message(
                    cid,
                    f"✅ Image uploaded: <b>{escape_html(display)}</b>\n\nType your prompt or tap Describe.",
                    parse_mode="HTML",
                    reply_markup=photo_keyboard(),
                )
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
                await send_message(cid, "❌ Failed to download voice message.")
                return JSONResponse({"ok": True})
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
                return JSONResponse({"ok": True})
            save_message(cid, "user", f"[Voice] {transcription}")
            current_parts: list = [{"text": transcription}]
            file_data = get_file_data(cid)
            if file_data and file_data.get("uri"):
                current_parts.append({"fileData": {"mimeType": file_data["mime_type"], "fileUri": file_data["uri"]}})
            elif file_data and file_data.get("base64"):
                current_parts.append({"inlineData": {"mimeType": file_data["mime_type"], "data": file_data["base64"]}})
            has_file = file_data is not None
            ai_response = await handle_gemini(cid, current_parts, get_system_text(name, cid), use_tools=not has_file)
            if ai_response and ai_response not in ("No response received from AI.", "Failed to parse AI response."):
                user_voice = get_user_voice(cid)
                tts_text = ai_response[:300]
                await send_chat_action(cid, "record_voice")
                audio_bytes = await generate_tts(tts_text, user_voice)
                if audio_bytes:
                    await send_voice_bytes(cid, audio_bytes, "🎙️ Voice response")
            return JSONResponse({"ok": True})

        if message.get("document"):
            ensure_user(cid, name)
            doc = message["document"]
            file_name = doc.get("file_name", "document")
            provided_mime = doc.get("mime_type", "")
            caption = message.get("caption", "").strip()
            file_info = await get_telegram_file_info(doc["file_id"])
            if not file_info:
                await send_message(cid, "❌ Failed to get file info.")
                return JSONResponse({"ok": True})
            file_path = file_info.get("file_path", file_name)
            mime = detect_mime_type(file_path, provided_mime)
            file_size = doc.get("file_size", 0)
            if file_size > 20 * 1024 * 1024:
                await send_message(cid, "⚠️ File too large. Maximum 20MB supported.")
                return JSONResponse({"ok": True})
            await send_chat_action(cid, "typing")
            await send_message(cid, f"📄 Uploading <b>{escape_html(file_name)}</b>...", parse_mode="HTML")
            file_bytes = await download_telegram_file(doc["file_id"])
            if not file_bytes:
                await send_message(cid, "❌ Failed to download file.")
                return JSONResponse({"ok": True})
            uploaded = await upload_to_gemini_files(file_bytes, mime, file_name)
            if not uploaded:
                await send_message(cid, "❌ Failed to upload file to AI engine. Try a different format.")
                return JSONResponse({"ok": True})
            if caption:
                save_message(cid, "user", f"[File: {file_name}] {caption}")
                parts_list3: list = [
                    {"text": caption},
                    {"fileData": {"mimeType": uploaded["mime_type"], "fileUri": uploaded["uri"]}},
                ]
                await handle_gemini(cid, parts_list3, get_system_text(name, cid), use_tools=False)
            else:
                set_state(cid, f"awaiting_file_prompt:{file_name}")
                await send_message(
                    cid,
                    f"✅ File uploaded: <b>{escape_html(file_name)}</b>\n\nType your prompt for this file.",
                    parse_mode="HTML",
                    reply_markup=file_prompt_keyboard(),
                )
            return JSONResponse({"ok": True})

        if message.get("audio"):
            ensure_user(cid, name)
            audio = message["audio"]
            file_name = audio.get("file_name", "audio.mp3")
            provided_mime = audio.get("mime_type", "audio/mpeg")
            caption = message.get("caption", "").strip()
            file_size = audio.get("file_size", 0)
            if file_size > 20 * 1024 * 1024:
                await send_message(cid, "⚠️ Audio too large. Maximum 20MB.")
                return JSONResponse({"ok": True})
            await send_chat_action(cid, "typing")
            await send_message(cid, f"🎵 Uploading <b>{escape_html(file_name)}</b>...", parse_mode="HTML")
            file_bytes = await download_telegram_file(audio["file_id"])
            if not file_bytes:
                await send_message(cid, "❌ Failed to download audio.")
                return JSONResponse({"ok": True})
            mime = detect_mime_type(file_name, provided_mime)
            uploaded = await upload_to_gemini_files(file_bytes, mime, file_name)
            if not uploaded:
                await send_message(cid, "❌ Failed to upload audio to AI engine.")
                return JSONResponse({"ok": True})
            if caption:
                save_message(cid, "user", f"[Audio: {file_name}] {caption}")
                parts_list4: list = [
                    {"text": caption},
                    {"fileData": {"mimeType": uploaded["mime_type"], "fileUri": uploaded["uri"]}},
                ]
                await handle_gemini(cid, parts_list4, get_system_text(name, cid), use_tools=False)
            else:
                set_state(cid, f"awaiting_file_prompt:{file_name}")
                await send_message(
                    cid,
                    f"✅ Audio uploaded: <b>{escape_html(file_name)}</b>\n\nType your prompt for this audio.",
                    parse_mode="HTML",
                    reply_markup=file_prompt_keyboard(),
                )
            return JSONResponse({"ok": True})

        if message.get("video") or message.get("video_note"):
            ensure_user(cid, name)
            video = message.get("video") or message.get("video_note", {})
            file_name = video.get("file_name", "video.mp4")
            provided_mime = video.get("mime_type", "video/mp4")
            caption = message.get("caption", "").strip()
            file_size = video.get("file_size", 0)
            if file_size > 20 * 1024 * 1024:
                await send_message(cid, "⚠️ Video too large. Maximum 20MB.")
                return JSONResponse({"ok": True})
            await send_chat_action(cid, "typing")
            await send_message(cid, f"🎬 Uploading <b>{escape_html(file_name)}</b>...", parse_mode="HTML")
            file_bytes = await download_telegram_file(video["file_id"])
            if not file_bytes:
                await send_message(cid, "❌ Failed to download video.")
                return JSONResponse({"ok": True})
            mime = detect_mime_type(file_name, provided_mime)
            uploaded = await upload_to_gemini_files(file_bytes, mime, file_name)
            if not uploaded:
                await send_message(cid, "❌ Failed to upload video to AI engine.")
                return JSONResponse({"ok": True})
            if caption:
                save_message(cid, "user", f"[Video: {file_name}] {caption}")
                parts_list5: list = [
                    {"text": caption},
                    {"fileData": {"mimeType": uploaded["mime_type"], "fileUri": uploaded["uri"]}},
                ]
                await handle_gemini(cid, parts_list5, get_system_text(name, cid), use_tools=False)
            else:
                set_state(cid, f"awaiting_file_prompt:{file_name}")
                await send_message(
                    cid,
                    f"✅ Video uploaded: <b>{escape_html(file_name)}</b>\n\nType your prompt for this video.",
                    parse_mode="HTML",
                    reply_markup=file_prompt_keyboard(),
                )
            return JSONResponse({"ok": True})

        if message.get("animation"):
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
                return JSONResponse({"ok": True})
            mime = detect_mime_type(file_name, provided_mime)
            uploaded = await upload_to_gemini_files(file_bytes, mime, file_name)
            if not uploaded:
                await send_message(cid, "❌ Failed to upload animation to AI engine.")
                return JSONResponse({"ok": True})
            if caption:
                save_message(cid, "user", f"[Animation: {file_name}] {caption}")
                parts_list6: list = [
                    {"text": caption},
                    {"fileData": {"mimeType": uploaded["mime_type"], "fileUri": uploaded["uri"]}},
                ]
                await handle_gemini(cid, parts_list6, get_system_text(name, cid), use_tools=False)
            else:
                set_state(cid, f"awaiting_file_prompt:{file_name}")
                await send_message(
                    cid,
                    f"✅ Animation uploaded: <b>{escape_html(file_name)}</b>\n\nType your prompt.",
                    parse_mode="HTML",
                    reply_markup=file_prompt_keyboard(),
                )
            return JSONResponse({"ok": True})

        if message.get("sticker"):
            ensure_user(cid, name)
            sticker = message["sticker"]
            if sticker.get("is_animated") or sticker.get("is_video"):
                await send_message(cid, "⚠️ Animated/video stickers are not supported. Send a static sticker.")
                return JSONResponse({"ok": True})
            await send_chat_action(cid, "typing")
            file_bytes = await download_telegram_file(sticker["file_id"])
            if not file_bytes:
                await send_message(cid, "❌ Failed to download sticker.")
                return JSONResponse({"ok": True})
            uploaded = await upload_to_gemini_files(file_bytes, "image/webp", "sticker.webp")
            if not uploaded:
                encoded = base64.b64encode(file_bytes).decode("utf-8")
                save_file_data(cid, {"uri": "", "mime_type": "image/webp", "name": "", "display_name": "sticker.webp", "base64": encoded})
                save_message(cid, "user", "[Sticker] Describe this sticker")
                parts_s: list = [
                    {"text": "Describe this sticker and react to it naturally."},
                    {"inlineData": {"mimeType": "image/webp", "data": encoded}},
                ]
                await handle_gemini(cid, parts_s, get_system_text(name, cid), use_tools=False)
            else:
                save_message(cid, "user", "[Sticker] Describe this sticker")
                parts_s2: list = [
                    {"text": "Describe this sticker and react to it naturally."},
                    {"fileData": {"mimeType": uploaded["mime_type"], "fileUri": uploaded["uri"]}},
                ]
                await handle_gemini(cid, parts_s2, get_system_text(name, cid), use_tools=False)
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