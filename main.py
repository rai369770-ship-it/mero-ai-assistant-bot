from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import httpx
import urllib.parse
import json
import re

app = FastAPI()

BOT_TOKEN = "8655216165:AAEoDExRbxAmZVxGL9H0na4hziBEv6I-0RA"
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
POOL_API = "https://mainsite-kcvz.onrender.com/tafb/key_pool.json?etag=1&n=2&client=key&maxage=1200"
MODEL = "gemini-2.5-flash"
SYSTEM_TEXT = "You're Mero AI assistant developed by Sujan Rai. You can analyze YouTube, generate images, answer questions, search the web and browse URLs. Always format responses using Markdown."

api_keys = []
conversations = {}

def escape_markdown_v2(text):
    escape_chars = r"_*[]()~`>#+-=|{}.!"
    return re.sub(f"([{re.escape(escape_chars)}])", r"\\\1", text)

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
        response = await client.post(url, data=payload)
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
        return None, "All API keys exhausted"

def get_messages(chat_id):
    if chat_id not in conversations:
        conversations[chat_id] = []
    return conversations[chat_id]

def build_body(messages, trimmed, youtube_url=None):
    contents = []
    for msg in messages[:-1]:
        role = "user" if msg["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": msg.get("text", "")}]})

    if youtube_url:
        contents.append({
            "role": "user",
            "parts": [
                {"text": trimmed},
                {"fileData": {"mimeType": "video/mp4", "fileUri": youtube_url}}
            ]
        })
        return {
            "system_instruction": {"parts": [{"text": SYSTEM_TEXT}]},
            "contents": contents,
            "generationConfig": {"maxOutputTokens": 65536}
        }

    contents.append({"role": "user", "parts": [{"text": trimmed}]})

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
        candidate = data["candidates"][0]
        grounding = candidate.get("groundingMetadata", {})
        chunks = grounding.get("groundingChunks", [])
        for chunk in chunks:
            web = chunk.get("web")
            if not web:
                continue
            url = web.get("uri")
            title = web.get("title") or "Source"
            if url and url not in seen:
                seen.add(url)
                sources.append({"title": title.strip(), "url": url.strip()})
    except Exception:
        pass
    return sources

def extract_ai_text(content):
    data = json.loads(content)
    if data.get("candidates"):
        candidate = data["candidates"][0]
        ai_text = ""
        parts = candidate.get("content", {}).get("parts", [])
        for p in parts:
            if p.get("text"):
                if ai_text:
                    ai_text += "\n"
                ai_text += p["text"]
        if not ai_text:
            return "No response received from AI.", []
        sources = extract_sources(data)
        return ai_text, sources
    return None, []

def format_response_with_sources(ai_text, sources):
    if not sources:
        return ai_text
    result = ai_text + "\n\n📌 Sources:\n"
    for s in sources:
        title = escape_markdown_v2(s["title"])
        url = s["url"]
        result += f"• [{title}]({url})\n"
    return result

async def handle_gemini(chat_id, messages, trimmed, youtube_url=None):
    body = build_body(messages, trimmed, youtube_url)
    json_body = json.dumps(body)
    success = await fetch_api_keys()
    if not success:
        error_msg = {"role": "model", "text": "Could not fetch API keys. Please check your internet connection."}
        messages.append(error_msg)
        await send_message(chat_id, error_msg["text"])
        return

    content, err = await try_api_call(json_body)
    if content:
        result = extract_ai_text(content)
        if result[0] and result[0] != "No response received from AI.":
            ai_text, sources = result
            formatted = format_response_with_sources(ai_text, sources)
            messages.append({"role": "model", "text": ai_text})
            escaped = escape_markdown_v2(formatted)
            await send_message(chat_id, escaped, parse_mode="MarkdownV2")
        elif result[0] == "No response received from AI.":
            messages.append({"role": "model", "text": result[0]})
            await send_message(chat_id, result[0])
        else:
            error = "Could not parse AI response. Please try again."
            messages.append({"role": "model", "text": error})
            await send_message(chat_id, error)
    else:
        error = f"Error: {err or 'Unknown error occurred'}"
        messages.append({"role": "model", "text": error})
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
            conversations[chat_id] = []
            welcome = (
                "✨ *Welcome to Mero AI Assistant\\!* ✨\n\n"
                "Your intelligent companion powered by *Gemini* ⚡\n\n"
                "💬 *Chat* — Type anything\n"
                "🎬 *YouTube* — `/youtube <url>` or `/youtube <url> <prompt>`\n"
                "🎨 *Image Gen* — `/imagine <description>`\n"
                "🌐 *Web Search* — Automatic when needed\n"
                "🔗 *URL Browse* — Send any URL\n"
                "🗑️ *Clear* — `/clear`\n\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "🚀 _Developed by Sujan Rai_"
            )
            await send_message(chat_id, welcome, parse_mode="MarkdownV2")
            return JSONResponse({"ok": True})

        if text == "/clear":
            conversations[chat_id] = []
            await send_message(chat_id, "🗑️ Conversation cleared\\.", parse_mode="MarkdownV2")
            return JSONResponse({"ok": True})

        if text.startswith("/imagine"):
            prompt = text.replace("/imagine", "", 1).strip()
            if not prompt:
                await send_message(chat_id, "Provide an image description\\.", parse_mode="MarkdownV2")
                return JSONResponse({"ok": True})

            await send_message(chat_id, "🎨 Generating image\\.\\.\\.", parse_mode="MarkdownV2")

            encoded_prompt = urllib.parse.quote(prompt)
            image_api_url = f"https://yabes-api.pages.dev/api/ai/image/dalle?prompt=={encoded_prompt}"

            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.get(image_api_url)
                    if response.status_code == 200:
                        resp_data = response.json()
                        if resp_data.get("success") and "output" in resp_data:
                            await send_photo(chat_id, resp_data["output"], "Here's your AI-generated image.")
                        else:
                            await send_message(chat_id, "Image generation failed.")
                    else:
                        await send_message(chat_id, f"Image API error {response.status_code}")
            except Exception as e:
                await send_message(chat_id, str(e))

            return JSONResponse({"ok": True})

        if text.startswith("/youtube"):
            yt_input = text.replace("/youtube", "", 1).strip()
            if not yt_input:
                await send_message(chat_id, "Provide a YouTube URL\\.", parse_mode="MarkdownV2")
                return JSONResponse({"ok": True})

            parts = yt_input.split(None, 1)
            yt_url = parts[0]
            prompt = parts[1] if len(parts) > 1 else "Analyze this YouTube video."

            await send_message(chat_id, "🎬 Processing video\\.\\.\\.", parse_mode="MarkdownV2")

            msgs = get_messages(chat_id)
            msgs.append({"role": "user", "text": f"{prompt} [YouTube: {yt_url}]"})

            await handle_gemini(chat_id, msgs, prompt, youtube_url=yt_url)

            return JSONResponse({"ok": True})

        if text.startswith("/"):
            return JSONResponse({"ok": True})

        trimmed = text.strip()

        await send_message(chat_id, "🤖 Thinking\\.\\.\\.", parse_mode="MarkdownV2")

        msgs = get_messages(chat_id)
        msgs.append({"role": "user", "text": trimmed})

        await handle_gemini(chat_id, msgs, trimmed)

        return JSONResponse({"ok": True})

    except Exception:
        return JSONResponse({"ok": True})