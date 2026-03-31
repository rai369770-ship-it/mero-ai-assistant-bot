import urllib.parse
from config import TEMPLATE_PROMPTS, SHARE_TEXT


def btn(text: str, callback_data: str) -> dict:
    return {"text": text, "callback_data": callback_data}


def url_btn(text: str, url: str) -> dict:
    return {"text": text, "url": url}


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
        [btn("🤖 AI Model", "set_model"), btn("🌡️ Temperature", "set_temp")],
        [btn("🗑️ Clear Chat", "clear"), btn("🧹 Clear Attachment", "cls")],
        [btn("💬 Feedback", "feedback_prompt"), btn("📜 History", "history")],
        [btn("🔄 Export Chat", "export_chat")],
        [btn("🛠 Developer & Credits", "developer_credits")],
        [btn("❌ Close", "close_settings")],
    ])


def admin_settings_keyboard() -> dict:
    return ikb([
        [btn("🧠 System Instructions", "set_system"), btn("🎙️ TTS Voice", "set_voice")],
        [btn("🤖 AI Model", "set_model"), btn("🌡️ Temperature", "set_temp")],
        [btn("🗑️ Clear Chat", "clear"), btn("🧹 Clear Attachment", "cls")],
        [btn("📊 Total Users", "admin_total"), btn("🚫 Banned Users", "admin_banned")],
        [btn("📢 Broadcast", "admin_broadcast")],
        [btn("📜 History", "history"), btn("🔄 Export Chat", "export_chat")],
        [btn("🛠 Developer & Credits", "developer_credits")],
        [btn("❌ Close", "close_settings")],
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


def model_keyboard() -> dict:
    return ikb([
        [btn("⚡ Mero Lite", "model:lite"), btn("🚀 Mero Pro", "model:pro")],
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
    return ikb([[btn("↩️ Reply Admin", f"reply_admin:{uid}")]])


def admin_user_reply_keyboard(target: int, username: str = "User") -> dict:
    return ikb([[btn(f"↩️ Message {username}", f"reply_user:{target}")]])


def broadcast_reply_keyboard() -> dict:
    return ikb([[btn("💬 Reply to Admin", "feedback_prompt")]])


def share_keyboard() -> dict:
    return ikb([
        [url_btn("📤 Share Now", f"https://t.me/share/url?url=https://t.me/MeroAIBot&text={urllib.parse.quote(SHARE_TEXT)}")],
    ])
