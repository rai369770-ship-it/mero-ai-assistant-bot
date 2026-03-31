import json
import httpx
from typing import Optional
from config import MODEL, CONTEXT_SIZE
from api_keys import fetch_api_keys, get_keys
from database import get_recent_history, save_message
from markdown_parse import markdown_to_html, escape_html
from message import send_message


async def try_api_call(body_json: str) -> tuple[Optional[str], Optional[str]]:
    keys = get_keys()
    if not keys:
        return None, "No API keys available"
    for i in range(len(keys)):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={keys[i]}"
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(url, content=body_json, headers={"Content-Type": "application/json"})
                if resp.status_code == 200:
                    return resp.text, None
        except Exception:
            continue
    return None, "All API keys exhausted"


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
        "generationConfig": {"maxOutputTokens": 4096},
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


async def call_gemini_raw(parts: list, system_text: str) -> Optional[str]:
    if not await fetch_api_keys():
        return None
    body = {
        "system_instruction": {"parts": [{"text": system_text}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"maxOutputTokens": 4096},
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