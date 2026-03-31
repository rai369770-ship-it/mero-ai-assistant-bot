import httpx
from config import POOL_API

api_keys: list[str] = []


async def fetch_api_keys() -> bool:
    global api_keys
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(POOL_API)
            if resp.status_code == 200:
                keys = resp.json()
                if isinstance(keys, list) and keys:
                    api_keys = keys
                    return True
    except Exception:
        pass
    return False


def get_keys() -> list[str]:
    return api_keys