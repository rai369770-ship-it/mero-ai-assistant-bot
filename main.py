from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import httpx
import urllib.parse
import json

app = FastAPI()

BOT_TOKEN = "8424346441:AAF7YxEtUeKvuNZ_nqGpEG2XVCwhhXBqFxU"
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
POOL_API = "https://mainsite-kcvz.onrender.com/tafb/key_pool.json?etag=1&n=2&client=key&maxage=1200"
MODEL = "gemini-2.5-flash"
SYSTEM_TEXT = "You're Mero AI assistant developed by sujan Rai. You can analyze and process YouTube, generate images, answer any question, search the web and browse a specific url."

api_keys = []
conversations = {}


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
    prev_chats = "\nPrevious conversation:"
    for msg in messages[:-1]:
        prev_chats += f"\n{msg['role']}: {msg.get('text', '')}"

    contents = []

    if youtube_url:
        for msg in messages[:-1]:
            role = "user" if msg["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": str(msg.get("text", ""))}]})
        current_parts = [
            {"text": trimmed},
            {"fileData": {"mimeType": "video/mp4", "fileUri": youtube_url}}
        ]
        contents.append({"role": "user", "parts": current_parts})
        return {
            "system_instruction": {"parts": [{"text": SYSTEM_TEXT + prev_chats}]},
            "contents": contents,
            "generationConfig": {"maxOutputTokens": 65536}
        }

    for msg in messages[:-1]:
        role = "user" if msg["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": str(msg.get("text", ""))}]})
    current_parts = []
    if trimmed:
        current_parts.append({"text": trimmed})
    if current_parts:
        contents.append({"role": "user", "parts": current_parts})
    return {
        "system_instruction": {"parts": [{"text": SYSTEM_TEXT + prev_chats}]},
        "contents": contents,
        "tools": [{"google_search": {}}, {"url_context": {}}],
        "generationConfig": {"maxOutputTokens": 65536}
    }


def extract_ai_text(content):
    data = json.loads(content)
    if data.get("candidates") and len(data["candidates"]) > 0:
        candidate = data["candidates"][0]
        ai_text = ""
        if candidate.get("content") and candidate["content"].get("parts"):
            for p in candidate["content"]["parts"]:
                if p.get("text"):
                    if ai_text:
                        ai_text += "\n"
                    ai_text += str(p["text"])
        if not ai_text:
            return "No response received from AI."
        return ai_text
    return None


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
        ai_text = extract_ai_text(content)
        if ai_text:
            model_msg = {"role": "model", "text": ai_text}
            messages.append(model_msg)
            await send_message(chat_id, ai_text)
        else:
            error_msg = {"role": "model", "text": "Could not parse AI response. Please try again."}
            messages.append(error_msg)
            await send_message(chat_id, error_msg["text"])
    else:
        error_msg = {"role": "model", "text": f"Error: {err or 'Unknown error occurred'}"}
        messages.append(error_msg)
        await send_message(chat_id, error_msg["text"])


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
                "👋 *Welcome to Mero AI Assistant!*\n\n"
                "• Ask anything by typing a simple prompt\n"
                "• /youtube <url> — Analyze YouTube videos\n"
                "• /imagine <prompt> — Generate AI images\n"
                "• /clear — Reset conversation\n\n"
                "Powered by Gemini 2.5 Flash ⚡"
            )
            await send_message(chat_id, welcome, parse_mode="Markdown")
            return JSONResponse({"ok": True})

        if text == "/clear":
            conversations[chat_id] = []
            await send_message(chat_id, "🗑️ Conversation cleared.")
            return JSONResponse({"ok": True})

        if text.startswith("/imagine"):
            prompt = text.replace("/imagine", "", 1).strip()
            if not prompt:
                await send_message(chat_id, "Please provide a description to generate an image.")
                return JSONResponse({"ok": True})
            await send_message(chat_id, "🎨 Generating image... Please wait.")
            encoded_prompt = urllib.parse.quote(prompt)
            image_api_url = f"https://yabes-api.pages.dev/api/ai/image/imagen3-0?prompt={encoded_prompt}&ratio=16%3A9"
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.get(image_api_url)
                    if response.status_code == 200:
                        resp_data = response.json()
                        if resp_data.get("success") and "url" in resp_data:
                            await send_photo(chat_id, resp_data["url"], "Here's your AI-generated image.")
                        else:
                            await send_message(chat_id, "Failed to generate image.")
                    else:
                        await send_message(chat_id, f"Image API returned status {response.status_code}.")
            except httpx.TimeoutException:
                await send_message(chat_id, "Request timeout. Please try again.")
            except Exception as e:
                await send_message(chat_id, f"An error occurred: {str(e)}")
            return JSONResponse({"ok": True})

        if text.startswith("/youtube"):
            yt_input = text.replace("/youtube", "", 1).strip()
            if not yt_input:
                await send_message(chat_id, "Please provide a YouTube URL.")
                return JSONResponse({"ok": True})
            parts = yt_input.split(None, 1)
            yt_url = parts[0]
            prompt = parts[1] if len(parts) > 1 else "Analyze this YouTube video in detail."
            await send_message(chat_id, "🎬 Processing YouTube video... Please wait.")
            msgs = get_messages(chat_id)
            user_display = f"{prompt} [YouTube: {yt_url}]"
            msgs.append({"role": "user", "text": user_display})
            try:
                await handle_gemini(chat_id, msgs, prompt, youtube_url=yt_url)
            except Exception as e:
                await send_message(chat_id, f"An error occurred: {str(e)}")
            return JSONResponse({"ok": True})

        if text.startswith("/"):
            return JSONResponse({"ok": True})

        trimmed = text.strip()
        await send_message(chat_id, "🤖 Thinking... Please wait.")
        msgs = get_messages(chat_id)
        msgs.append({"role": "user", "text": trimmed})
        try:
            await handle_gemini(chat_id, msgs, trimmed)
        except Exception as e:
            await send_message(chat_id, f"An error occurred: {str(e)}")
        return JSONResponse({"ok": True})
    except Exception as e:
        print(f"Error: {str(e)}")
        return JSONResponse({"ok": True})