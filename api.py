import json
import httpx
from typing import Optional
from config import CONTEXT_SIZE
from api_keys import fetch_api_keys, get_keys
from database import get_recent_history, save_message, get_user_model
from markdown_parse import markdown_to_html, escape_html
from message import send_message


def _ordered_keys(preferred_key: Optional[str] = None) -> list[str]:
    keys = [key for key in get_keys() if key]
    if preferred_key and preferred_key in keys:
        return [preferred_key] + [k for k in keys if k != preferred_key]
    return keys


def _normalize_part_keys(part: dict) -> dict:
    def _compact(data: dict) -> dict:
        return {k: v for k, v in data.items() if v not in ("", None)}

    if "file_data" in part and isinstance(part["file_data"], dict):
        fd = part["file_data"]
        normalized = _compact({
            "mime_type": fd.get("mime_type") or fd.get("mimeType"),
            "file_uri": fd.get("file_uri") or fd.get("fileUri"),
        })
        return {"file_data": normalized} if normalized else {}
    if "fileData" in part and isinstance(part["fileData"], dict):
        fd = part["fileData"]
        normalized = _compact({
            "mime_type": fd.get("mimeType"),
            "file_uri": fd.get("fileUri"),
        })
        return {"file_data": normalized} if normalized else {}
    if "inline_data" in part and isinstance(part["inline_data"], dict):
        ind = part["inline_data"]
        normalized = _compact({
            "mime_type": ind.get("mime_type") or ind.get("mimeType"),
            "data": ind.get("data"),
        })
        return {"inline_data": normalized} if normalized else {}
    if "inlineData" in part and isinstance(part["inlineData"], dict):
        ind = part["inlineData"]
        normalized = _compact({
            "mime_type": ind.get("mimeType"),
            "data": ind.get("data"),
        })
        return {"inline_data": normalized} if normalized else {}
    if "text" in part:
        return {"text": part.get("text", "")}
    return part


def _normalize_parts(parts: list) -> list:
    normalized: list = []
    for part in parts:
        if isinstance(part, dict):
            candidate = _normalize_part_keys(part)
            if candidate:
                normalized.append(candidate)
        else:
            normalized.append(part)
    return normalized


async def try_api_call(body_json: str, model: str, preferred_key: Optional[str] = None) -> tuple[Optional[str], Optional[str]]:
    keys = _ordered_keys(preferred_key)
    if not keys:
        return None, "No API keys available"
    failures: list[str] = []
    async with httpx.AsyncClient(timeout=120.0) as client:
        for idx, key in enumerate(keys, start=1):
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
            try:
                resp = await client.post(url, content=body_json, headers={"Content-Type": "application/json"})
            except Exception as exc:
                failures.append(f"key#{idx}: request_error:{exc.__class__.__name__}")
                continue
            if resp.status_code == 200:
                return resp.text, None
            failures.append(f"key#{idx}: status_{resp.status_code}")
    return None, "; ".join(failures) if failures else "All API keys exhausted"


def build_body(history_messages: list[dict], current_parts: list, system_text: str, use_tools: bool = True) -> dict:
    contents = []
    for msg in history_messages:
        contents.append({
            "role": "user" if msg["role"] == "user" else "model",
            "parts": [{"text": msg.get("text", "")}]
        })
    contents.append({"role": "user", "parts": _normalize_parts(current_parts)})
    body: dict = {
        "system_instruction": {"parts": [{"text": system_text}]},
        "contents": contents,
        "generationConfig": {"maxOutputTokens": 8192},
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
        html += "".join(f'• <a href="{escape_html(s["url"])}">{escape_html(s["title"])}</a>\n' for s in sources)
    return html


async def call_gemini_raw(parts: list, system_text: str, model: str = "gemini-2.5-flash-lite", preferred_key: Optional[str] = None) -> Optional[str]:
    if not await fetch_api_keys():
        return None
    body = {
        "system_instruction": {"parts": [{"text": system_text}]},
        "contents": [{"role": "user", "parts": _normalize_parts(parts)}],
        "generationConfig": {"maxOutputTokens": 8192},
    }
    content, _ = await try_api_call(json.dumps(body), model, preferred_key=preferred_key)
    if not content:
        return None
    text, _ = extract_ai_text(content)
    return text


async def handle_gemini(cid: int, current_parts: list, system_text: str, use_tools: bool = True, preferred_key: Optional[str] = None) -> Optional[str]:
    history = get_recent_history(cid, CONTEXT_SIZE)
    body = build_body(history, current_parts, system_text, use_tools)
    if not await fetch_api_keys():
        msg = "Could not fetch API keys. Please try again later."
        save_message(cid, "model", msg)
        await send_message(cid, msg)
        return None
    model = get_user_model(cid)
    content, err = await try_api_call(json.dumps(body), model, preferred_key=preferred_key)
    if content:
        ai_text, sources = extract_ai_text(content)
        save_message(cid, "model", ai_text)
        if ai_text not in ("No response received from AI.", "Failed to parse AI response."):
            formatted = format_response_with_sources(ai_text, sources)
            await send_message(cid, formatted, parse_mode="HTML")
        else:
            await send_message(cid, ai_text)
        return ai_text
    error = f"Error: {err or 'Unknown error occurred'}"
    save_message(cid, "model", error)
    await send_message(cid, error)
    return None
