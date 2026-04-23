import ast
import re

from database import get_file_data, get_memories, save_agent_context, save_memory, save_message
from message import send_message
from api import call_gemini_raw, handle_gemini
from system import get_system_text
from image_generation import execute_image
from texttopdf import execute_text_to_pdf
from settings import ikb, btn
from config import AGENT_PROMPT


def processYoutube(prompt: str, link: str) -> dict:
    return {"prompt": (prompt or "").strip() or "Summarize and transcribe this YouTube video", "url": (link or "").strip()}


def _extract_calls(response: str) -> list[str]:
    cleaned = re.sub(r"```python\s*", "", response or "")
    cleaned = re.sub(r"```\s*", "", cleaned).strip()
    calls = re.findall(r"\b[A-Za-z_]\w*\([^()\n]*(?:\([^()\n]*\)[^()\n]*)*\)", cleaned)
    if not calls:
        lines = [ln.strip() for ln in cleaned.splitlines() if ln.strip()]
        for line in lines:
            if "(" in line and line.endswith(")"):
                calls.append(line)
    return calls[:2]


def _safe_eval_string(node: ast.AST) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.strip()
    if isinstance(node, ast.Name):
        return node.id.strip()
    return ""


def _parse_call(call: str) -> tuple[str, list[str], dict[str, str]]:
    try:
        expr = ast.parse(call, mode="eval").body
    except Exception:
        return "", [], {}
    if not isinstance(expr, ast.Call):
        return "", [], {}
    if isinstance(expr.func, ast.Name):
        fn_name = expr.func.id
    else:
        return "", [], {}
    args = [_safe_eval_string(arg) for arg in expr.args]
    kwargs = {}
    for kw in expr.keywords:
        if not kw.arg:
            continue
        kwargs[kw.arg] = _safe_eval_string(kw.value)
    return fn_name, args, kwargs


def _clean_placeholder(value: str, fallback: str) -> str:
    cleaned = (value or "").strip()
    lowered = cleaned.lower()
    placeholders = {
        "",
        "prompt",
        "query",
        "user_prompt",
        "{prompt}",
        "{query}",
        "{user_prompt}",
        "query=",
        "prompt=",
        "query =",
        "prompt =",
    }
    if lowered in placeholders or lowered.startswith("query=") or lowered.startswith("prompt="):
        return fallback
    return cleaned


def _is_youtube_url(url: str) -> bool:
    candidate = (url or "").strip()
    return bool(re.match(r"^https?://(?:www\.)?(?:youtube\.com|m\.youtube\.com|youtu\.be)/", candidate, flags=re.IGNORECASE))


def parse_agent_actions(response: str) -> list[tuple[str, dict]]:
    calls = _extract_calls(response)
    actions: list[tuple[str, dict]] = []
    for call in calls:
        fn_name, args, kwargs = _parse_call(call)
        low = fn_name.lower().strip()
        if low.startswith("processyoutube") or low.startswith("sendyoutube"):
            prompt = kwargs.get("prompt") or (args[0] if len(args) > 0 else "")
            link = kwargs.get("link") or kwargs.get("url") or (args[1] if len(args) > 1 else "")
            actions.append(("youtube", processYoutube(prompt, link)))
            continue
        if low.startswith("sendnormalmessage"):
            query = kwargs.get("query") or (args[0] if args else "")
            actions.append(("normal", {"query": query}))
            continue
        if low.startswith("generateimage"):
            query = kwargs.get("query") or (args[0] if args else "")
            actions.append(("image", {"query": query}))
            continue
        if low.startswith("texttopdf"):
            prompt = kwargs.get("prompt") or (args[0] if args else "")
            actions.append(("texttopdf", {"prompt": prompt}))
            continue
        if low.startswith("savememory"):
            mem = kwargs.get("memory") or (args[1] if len(args) > 1 else "")
            actions.append(("save_memory", {"memory": mem}))
            continue
    return actions


async def execute_normal_message(cid: int, query: str, name: str) -> None:
    save_message(cid, "user", query)
    current_parts: list = [{"text": query}]
    file_data = get_file_data(cid)
    has_file = False
    if file_data and file_data.get("base64"):
        current_parts.append({"inlineData": {"mimeType": file_data["mime_type"], "data": file_data["base64"]}})
        has_file = True
    save_agent_context(cid, {"prompt": query, "attachments": file_data or {}})
    await handle_gemini(
        cid,
        current_parts,
        get_system_text(name, cid),
        use_tools=not has_file,
    )


async def execute_youtube(cid: int, prompt: str, url: str, name: str) -> None:
    if not _is_youtube_url(url):
        await execute_normal_message(cid, f"{prompt}\n\nURL: {url}".strip(), name)
        return
    await send_message(cid, "🎬 Processing YouTube link...", reply_markup=ikb([[btn("⏳ Please wait...", "noop")]]))
    save_message(cid, "user", f"{prompt} [YouTube: {url}]")
    save_agent_context(cid, {"prompt": prompt, "attachments": {"youtube_url": url}})
    youtube_prompt = (
        f"Task: {prompt}\n"
        f"YouTube URL: {url}\n\n"
        "Analyze this public YouTube URL directly via Gemini video understanding. "
        "Summarize spoken content and key visual events. "
        "Include MM:SS timestamps for important moments when possible. "
        "If details are unclear, state limitations clearly."
    )
    parts = [
        {"file_data": {"file_uri": url}},
        {"text": youtube_prompt},
    ]
    await handle_gemini(cid, parts, get_system_text(name, cid), use_tools=False, model="gemini-2.5-flash")


async def agent_route(cid: int, user_text: str, name: str) -> None:
    agent_system = (
        "You're an AI agent for a telegram bot built with python. "
        "Only output function call lines. Never reply to user directly."
    )
    formatted_memories = "\n".join(f"- {m}" for m in get_memories(cid)) or "- (none)"
    prompt = AGENT_PROMPT.format(user_prompt=user_text) + f"\n\nMemories: (formattedMemories)\n{formatted_memories}"
    file_data = get_file_data(cid)
    save_agent_context(cid, {"prompt": user_text, "attachments": file_data or {}})
    agent_response = await call_gemini_raw([{"text": prompt}], agent_system, model="gemini-2.5-flash-lite")
    actions = parse_agent_actions(agent_response or "")
    if not actions:
        await execute_normal_message(cid, user_text, name)
        return

    for action, params in actions:
        resolved_query = _clean_placeholder(params.get("query", user_text), user_text)
        resolved_prompt = _clean_placeholder(params.get("prompt", user_text), user_text)
        match action:
            case "youtube":
                video_url = _clean_placeholder(params.get("url", ""), "")
                await execute_youtube(cid, resolved_prompt or "Analyze this video", video_url, name)
            case "image":
                await execute_image(cid, resolved_query or user_text, name)
            case "texttopdf":
                await execute_text_to_pdf(cid, resolved_prompt or user_text)
            case "save_memory":
                if params.get("memory"):
                    save_memory(cid, params["memory"])
            case "normal":
                await execute_normal_message(cid, resolved_query or user_text, name)
            case _:
                await execute_normal_message(cid, user_text, name)
