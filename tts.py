import httpx
import urllib.parse
from typing import Optional
from config import TTS_API, DEFAULT_VOICE


async def generate_tts(text: str, voice: str = DEFAULT_VOICE) -> Optional[bytes]:
    encoded = urllib.parse.quote(text[:300])
    url = f"{TTS_API}/tts?voice={voice}&text={encoded}"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200 and len(resp.content) > 100:
                return resp.content
    except Exception:
        pass
    return None