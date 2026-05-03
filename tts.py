import httpx
import urllib.parse
from typing import Optional
from config import MICROSOFT_TTS_API, DEFAULT_TTS_VOICE

MICROSOFT_VOICES_CACHE: list[dict] = []
MICROSOFT_VOICES_CACHE_TIMESTAMP: float = 0
CACHE_TTL = 3600  # 1 hour cache


async def fetch_microsoft_voices() -> list[dict]:
    """Fetch available Microsoft TTS voices from API."""
    global MICROSOFT_VOICES_CACHE, MICROSOFT_VOICES_CACHE_TIMESTAMP
    import time
    current_time = time.time()
    
    if MICROSOFT_VOICES_CACHE and (current_time - MICROSOFT_VOICES_CACHE_TIMESTAMP) < CACHE_TTL:
        return MICROSOFT_VOICES_CACHE
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{MICROSOFT_TTS_API}/voices")
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    voices = data.get("voices", [])
                    # Sort by language, then gender (female first), then name
                    def sort_key(v):
                        gender_priority = 0 if v.get("gender", "").lower() == "female" else 1
                        return (v.get("language", ""), gender_priority, v.get("name", ""))
                    sorted_voices = sorted(voices, key=sort_key)
                    MICROSOFT_VOICES_CACHE = sorted_voices
                    MICROSOFT_VOICES_CACHE_TIMESTAMP = current_time
                    return sorted_voices
    except Exception:
        pass
    return MICROSOFT_VOICES_CACHE or []


async def generate_tts(text: str, voice: str = DEFAULT_TTS_VOICE) -> Optional[bytes]:
    """Generate TTS audio using Microsoft Azure Neural TTS."""
    encoded_text = urllib.parse.quote(text[:300])
    url = f"{MICROSOFT_TTS_API}?voice={urllib.parse.quote(voice)}&text={encoded_text}"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(url)
            content_type = resp.headers.get("content-type", "")
            if resp.status_code == 200 and ("audio" in content_type.lower() or resp.content) and len(resp.content) > 100:
                return resp.content
    except Exception:
        pass
    return None
