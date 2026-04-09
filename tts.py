import httpx
import urllib.parse
from typing import Optional
from config import TTS_API, DEFAULT_TTS_LANG
from languages import SUPPORTED_LANGUAGE_CODES


async def generate_tts(text: str, lang: str = DEFAULT_TTS_LANG) -> Optional[bytes]:
    lang_code = lang if lang in SUPPORTED_LANGUAGE_CODES else DEFAULT_TTS_LANG
    encoded = urllib.parse.quote(text[:300])
    url = f"{TTS_API}?text={encoded}&lang={urllib.parse.quote(lang_code)}"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(url)
            content_type = resp.headers.get("content-type", "")
            if resp.status_code == 200 and "audio" in content_type.lower() and len(resp.content) > 100:
                return resp.content
    except Exception:
        pass
    return None
