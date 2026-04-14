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
    lines = [ln.strip() for ln in cleaned.splitlines() if ln.strip()]
    calls: list[str] = []
    for line in lines:
        if "(" in line and line.endswith(")"):
            calls.append(line)
    return calls[:2]


def _extract_arg(call: str) -> str:
    m = re.search(r"\((.*)\)$", call)
    if not m:
        return ""
    return m.group(1).strip()


def parse_agent_actions(response: str) -> list[tuple[str, dict]]:
    calls = _extract_calls(response)
    actions: list[tuple[str, dict]] = []
    for call in calls:
        low = call.lower()
        if low.startswith("processyoutube") or low.startswith("sendyoutube"):
            parts = _extract_arg(call).split(",", 1)
            if len(parts) == 2:
                actions.append(("youtube", processYoutube(parts[0].strip().strip('"\''), parts[1].strip().strip('"\''))))
            continue
        if low.startswith("sendnormalmessage"):
            actions.append(("normal", {"query": _extract_arg(call).strip('"\'' )}))
            continue
        if low.startswith("generateimage"):
            actions.append(("image", {"query": _extract_arg(call).strip('"\'' )}))
            continue
        if low.startswith("texttopdf"):
            actions.append(("texttopdf", {"prompt": _extract_arg(call).strip('"\'' )}))
            continue
        if low.startswith("savememory"):
            arg_text = _extract_arg(call)
            mem = arg_text.split(",", 1)[1].strip().strip('"\'') if "," in arg_text else ""
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
    await send_message(cid, "🎬 Processing YouTube link...", reply_markup=ikb([[btn("⏳ Please wait...", "noop")]]))
    save_message(cid, "user", f"{prompt} [YouTube: {url}]")
    save_agent_context(cid, {"prompt": prompt, "attachments": {"youtube_url": url}})
    youtube_prompt = (
        f"Task: {prompt}\n"
        f"YouTube URL: {url}\n\n"
        "Use Gemini video understanding for this YouTube URL. "
        "If transcript/audio is available, summarize spoken content with timestamps. "
        "Also summarize key visual events. "
        "If exact details are unavailable, clearly state limitations and still provide best-effort analysis."
    )
    parts = [
        {"file_data": {"mime_type": "video/*", "file_uri": url}},
        {"text": youtube_prompt},
    ]
    await handle_gemini(cid, parts, get_system_text(name, cid), use_tools=False)


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
        resolved_query = params.get("query", user_text)
        resolved_prompt = params.get("prompt", user_text)
        if resolved_query in ("prompt", "user_prompt", "{prompt}"):
            resolved_query = user_text
        if resolved_prompt in ("prompt", "user_prompt", "{prompt}"):
            resolved_prompt = user_text
        match action:
            case "youtube":
                await execute_youtube(cid, resolved_prompt or "Analyze this video", params.get("url", ""), name)
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
