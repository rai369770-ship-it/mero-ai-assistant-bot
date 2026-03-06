from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import httpx
import urllib.parse
import json
import re
import os
import redis

app = FastAPI()

BOT_TOKEN = "8655216165:AAEoDExRbxAmZVxGL9H0na4hziBEv6I-0RA"
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
POOL_API = "https://sr-pool-api.pages.dev"
MODEL = "gemini-2.5-flash"
SYSTEM_TEXT = "You're Mero AI assistant developed by Sujan Rai. You can analyze YouTube videos, generate images, answer questions, search the web, browse URLs, write code, translate languages, summarize text, solve math problems, and have natural conversations. Always provide helpful, accurate, and well-structured responses. you can show emotions. you've emotions."

REDIS_URL = os.environ.get("REDIS_URL", "")
r = redis.from_url(REDIS_URL, decode_responses=True)

api_keys = []

MAX_HISTORY = 30
CONTEXT_SIZE = 5


def get_history_key(chat_id):
    return f"chat:{chat_id}:history"


def save_message(chat_id, role, text):
    key = get_history_key(chat_id)
    count = r.llen(key)
    if count >= MAX_HISTORY * 2:
        r.delete(key)
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
    key = get_history_key(chat_id)
    r.delete(key)


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
            if code_lang:
                result.append(f"<pre><code class=\"language-{escape_html(code_lang)}\">{code_content}</code></pre>")
            else:
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


def build_body(history_messages, current_text, youtube_url=None):
    contents = []

    for msg in history_messages:
        role = "user" if msg["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": msg.get("text", "")}]})

    if youtube_url:
        contents.append({
            "role": "user",
            "parts": [
                {"text": current_text},
                {"fileData": {"mimeType": "video/mp4", "fileUri": youtube_url}}
            ]
        })
        return {
            "system_instruction": {"parts": [{"text": SYSTEM_TEXT}]},
            "contents": contents,
            "generationConfig": {"maxOutputTokens": 65536}
        }

    contents.append({"role": "user", "parts": [{"text": current_text}]})

    return {
        "system_instruction": {"parts": [{"text": SYSTEM_TEXT}]},
        "contents": contents,
        "tools": [{"google_search": {}}, {"url_context": {}}],
        "generationConfig": {"maxOutputTokens": 65536}
    }


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
        if not chunks:
            support = grounding.get("groundingSupports", [])
            for s in support:
                segment = s.get("segment", {})
                refs = s.get("groundingChunkIndices", [])
                for ref_chunk in grounding.get("groundingChunks", []):
                    web = ref_chunk.get("web")
                    if web:
                        uri = web.get("uri", "")
                        title = web.get("title", "Source")
                        if uri and uri not in seen:
                            seen.add(uri)
                            sources.append({"title": title.strip(), "url": uri.strip()})
            search_queries = grounding.get("webSearchQueries", [])
            retrieval = grounding.get("retrievalQueries", [])
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


async def handle_gemini(chat_id, current_text, youtube_url=None):
    history = get_recent_history(chat_id, CONTEXT_SIZE)
    body = build_body(history, current_text, youtube_url)
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
        if ai_text and ai_text != "No response received from AI." and ai_text != "Failed to parse AI response.":
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

        if "text" not in message:
            return JSONResponse({"ok": True})

        text = message["text"]

        if text == "/start":
            clear_history(chat_id)
            welcome = (
                "✨ <b>Welcome to Mero AI Assistant!</b> ✨\n\n"
                "Your intelligent companion powered by <b>Gemini 2.5 Flash</b> ⚡\n\n"
                "<b>Here's what I can do:</b>\n\n"
                "💬 <b>Chat</b> — Just type anything to start a conversation\n"
                "🎬 <b>YouTube Analysis</b> — <code>/youtube &lt;url&gt;</code> or <code>/youtube &lt;url&gt; &lt;prompt&gt;</code>\n"
                "🎨 <b>Image Generation</b> — <code>/imagine &lt;description&gt;</code>\n"
                "🌐 <b>Web Search</b> — Automatically searches when needed\n"
                "🔗 <b>URL Browsing</b> — Send any URL to get a summary\n"
                "📝 <b>Code Writing</b> — Ask me to write code in any language\n"
                "🌍 <b>Translation</b> — Translate text between languages\n"
                "📊 <b>Math &amp; Science</b> — Solve equations and explain concepts\n"
                "📖 <b>Summarization</b> — Summarize articles, documents, or text\n"
                "📜 <b>Chat History</b> — <code>/history</code> to view your conversation\n"
                "🗑️ <b>Clear Chat</b> — <code>/clear</code> to start fresh\n\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "I remember your last 5 conversations for context.\n"
                "Up to 30 messages are stored in history.\n\n"
                "🚀 <i>Developed by Sujan Rai</i>"
            )
            await send_message(chat_id, welcome, parse_mode="HTML")
            return JSONResponse({"ok": True})

        if text == "/clear":
            clear_history(chat_id)
            await send_message(chat_id, "🗑️ Conversation cleared.", parse_mode="HTML")
            return JSONResponse({"ok": True})

        if text == "/history":
            history = get_all_history(chat_id)
            if not history:
                await send_message(chat_id, "📜 No conversation history found.")
                return JSONResponse({"ok": True})

            await send_message(chat_id, f"📜 <b>Your Conversation History ({len(history)} messages):</b>", parse_mode="HTML")

            for i, msg in enumerate(history):
                role_label = "👤 You" if msg["role"] == "user" else "🤖 Mero AI"
                msg_text = msg.get("text", "")
                if len(msg_text) > 3000:
                    msg_text = msg_text[:3000] + "..."
                formatted = f"<b>{role_label}:</b>\n{escape_html(msg_text)}"
                await send_message(chat_id, formatted, parse_mode="HTML")

            return JSONResponse({"ok": True})

        if text.startswith("/imagine"):
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

            await handle_gemini(chat_id, prompt, youtube_url=yt_url)

            return JSONResponse({"ok": True})

        if text.startswith("/"):
            await send_message(chat_id, "Unknown command. Type /start to see available commands.")
            return JSONResponse({"ok": True})

        trimmed = text.strip()

        await send_message(chat_id, "🤖 Thinking...")

        save_message(chat_id, "user", trimmed)

        await handle_gemini(chat_id, trimmed)

        return JSONResponse({"ok": True})

    except Exception:
        return JSONResponse({"ok": True})