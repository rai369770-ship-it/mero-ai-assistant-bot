import re
from database import save_message, get_file_data
from message import send_message
from api import call_gemini_raw, handle_gemini
from system import get_system_text
from image_generation import execute_image
from texttopdf import execute_text_to_pdf
from settings import ikb, btn
from config import AGENT_PROMPT


def parse_agent_response(response: str) -> tuple[str, dict]:
    cleaned = re.sub(r"```python\s*", "", response)
    cleaned = re.sub(r"```\s*", "", cleaned).strip()

    if (m := re.search(r"sendYouTube\(\s*[\"'](.+?)[\"']\s*,\s*[\"'](.+?)[\"']\s*\)", cleaned)):
        return "youtube", {"prompt": m.group(1), "url": m.group(2)}
    if (m := re.search(r"sendYouTube\(\s*(.+?)\s*,\s*[\"'](.+?)[\"']\s*\)", cleaned)):
        return "youtube", {"prompt": m.group(1).strip("\"'"), "url": m.group(2)}
    if (m := re.search(r"sendYouTube\(\s*[\"'](.+?)[\"']\s*,\s*(.+?)\s*\)", cleaned)):
        return "youtube", {"prompt": m.group(1), "url": m.group(2).strip("\"'")}

    if (m := re.search(r"sendNormalMessage\(\s*[\"'](.+?)[\"']\s*\)", cleaned, flags=re.IGNORECASE)):
        return "normal", {"query": m.group(1)}
    if (m := re.search(r"sendNormalMessage\(\s*(.+?)\s*\)", cleaned, flags=re.IGNORECASE)):
        return "normal", {"query": m.group(1).strip("\"'")}

    if re.search(r"generateImage\s*\(", cleaned, flags=re.IGNORECASE):
        return "image", {}

    if (m := re.search(r'texttopdf\(\s*["\'](.+?)["\']\s*\)', cleaned, flags=re.IGNORECASE)):
        return "texttopdf", {"prompt": m.group(1)}
    if (m := re.search(r"texttopdf\(\s*(.+?)\s*\)", cleaned, flags=re.IGNORECASE)):
        return "texttopdf", {"prompt": m.group(1).strip("\"'")}

    return "normal", {}


async def execute_normal_message(cid: int, query: str, name: str) -> None:
    save_message(cid, "user", query)
    current_parts: list = [{"text": query}]
    file_data = get_file_data(cid)
    has_file = False
    if file_data and file_data.get("base64"):
        current_parts.append({"inlineData": {"mimeType": file_data["mime_type"], "data": file_data["base64"]}})
        has_file = True
    await handle_gemini(
        cid,
        current_parts,
        get_system_text(name, cid),
        use_tools=not has_file,
    )


async def execute_youtube(cid: int, prompt: str, url: str, name: str) -> None:
    await send_message(cid, "🎬 Processing YouTube link...", reply_markup=ikb([[btn("⏳ Please wait...", "noop")]]))
    save_message(cid, "user", f"{prompt} [YouTube: {url}]")
    youtube_prompt = (
        f"{prompt}\n\n"
        "Analyze the provided YouTube URL. "
        "If transcript is available, use it. Otherwise analyze from available page context and provide a best-effort summary."
    )
    parts = [
        {"text": youtube_prompt},
        {"file_data": {"mime_type": "text/html", "file_uri": url}},
    ]
    await handle_gemini(cid, parts, get_system_text(name, cid), use_tools=True)


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
        case "texttopdf":
            await execute_text_to_pdf(cid, params.get("prompt", user_text))
        case "normal":
            await execute_normal_message(cid, params.get("query", user_text), name)
        case _:
            await execute_normal_message(cid, user_text, name)
