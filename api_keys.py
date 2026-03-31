import httpx
from config import POOL_API

api_keys: list[str] = []
key_turn: int = 0


async def fetch_api_keys() -> bool:
    global api_keys, key_turn
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(POOL_API)
            if resp.status_code == 200:
                keys = resp.json()
                if isinstance(keys, list) and keys:
                    api_keys = [k for k in keys if isinstance(k, str) and k]
                    if not api_keys:
                        return False
                    key_turn %= len(api_keys)
                    return True
    except Exception:
        pass
    return False


def get_keys() -> list[str]:
    return api_keys


def get_keys_turn_by_turn() -> list[str]:
    global key_turn
    keys = get_keys()
    if not keys:
        return []
    start = key_turn % len(keys)
    ordered = keys[start:] + keys[:start]
    key_turn = (start + 1) % len(keys)
    return ordered
