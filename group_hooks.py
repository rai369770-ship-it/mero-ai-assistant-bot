import re
from typing import Optional

from config import BOT_USERNAME, BOT_MENTION_ALIASES


def is_group_chat(message: dict) -> bool:
    chat_type = (message.get("chat") or {}).get("type", "")
    return chat_type in {"group", "supergroup"}


def extract_group_prompt(message: dict) -> Optional[str]:
    """Return cleaned prompt only when the bot is explicitly mentioned in a group message."""
    text = (message.get("text") or "").strip()
    if not text:
        return None

    aliases = {a.lower().lstrip("@") for a in BOT_MENTION_ALIASES if a}
    if BOT_USERNAME:
        aliases.add(BOT_USERNAME.lower().lstrip("@"))

    if not aliases:
        return None

    for alias in aliases:
        pattern = rf"^\s*@{re.escape(alias)}\b[\s,:-]*(.*)$"
        m = re.match(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if m:
            prompt = (m.group(1) or "").strip()
            return prompt or None
    return None
