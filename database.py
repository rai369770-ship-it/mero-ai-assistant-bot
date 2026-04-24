import json
import redis.asyncio as redis
from typing import Optional
from config import REDIS_URL, MAX_HISTORY

# Global Redis connection pool
_redis_pool: Optional[redis.Redis] = None


async def get_redis() -> redis.Redis:
    """Get or create Redis connection with connection pooling."""
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = redis.from_url(REDIS_URL, decode_responses=True, max_connections=20)
    return _redis_pool


def hk(cid: int) -> str:
    return f"chat:{cid}:history"


def rsk(cid: int) -> str:
    return f"chat:{cid}:reply_state"


def sk(cid: int) -> str:
    return f"chat:{cid}:state"


def fk(cid: int) -> str:
    return f"chat:{cid}:file"


async def save_user(uid: int, name: str) -> None:
    r = await get_redis()
    await r.hset("totalUsers", str(uid), name)


async def user_exists(uid: int) -> bool:
    r = await get_redis()
    return await r.hexists("totalUsers", str(uid))


async def remove_all_user_data(uid: int) -> None:
    r = await get_redis()
    await r.delete(hk(uid), rsk(uid), sk(uid), fk(uid))
    await r.delete(f"settings:{uid}:system", f"settings:{uid}:voice", f"settings:{uid}:temp", f"settings:{uid}:model")
    await r.hdel("totalUsers", str(uid))


async def get_all_users() -> dict[str, str]:
    r = await get_redis()
    return await r.hgetall("totalUsers")


async def ban_user(uid: int, name: str) -> None:
    r = await get_redis()
    await r.hset("bannedUsers", str(uid), name)


async def unban_user(uid: int) -> None:
    r = await get_redis()
    await r.hdel("bannedUsers", str(uid))


async def is_banned(uid: int) -> bool:
    r = await get_redis()
    return await r.hexists("bannedUsers", str(uid))


async def get_banned_users() -> dict[str, str]:
    r = await get_redis()
    return await r.hgetall("bannedUsers")


async def save_message(cid: int, role: str, text: str) -> None:
    r = await get_redis()
    key = hk(cid)
    # Batch trim operation - only trim when necessary
    current_len = await r.llen(key)
    if current_len >= MAX_HISTORY * 2:
        pipe = r.pipeline()
        pipe.ltrim(key, -((MAX_HISTORY - 1) * 2), -1)
        pipe.rpush(key, json.dumps({"role": role, "text": text}))
        await pipe.execute()
    else:
        await r.rpush(key, json.dumps({"role": role, "text": text}))


async def get_all_history(cid: int) -> list[dict]:
    r = await get_redis()
    return [json.loads(i) for i in await r.lrange(hk(cid), 0, -1)]


async def get_recent_history(cid: int, count: int) -> list[dict]:
    r = await get_redis()
    key = hk(cid)
    total = await r.llen(key)
    if total == 0:
        return []
    start = max(0, total - count * 2)
    return [json.loads(i) for i in await r.lrange(key, start, -1)]


async def clear_history(cid: int) -> None:
    r = await get_redis()
    await r.delete(hk(cid))


async def set_reply_state(cid: int, target: int) -> None:
    r = await get_redis()
    await r.set(rsk(cid), str(target), ex=3600)


async def get_reply_state(cid: int) -> Optional[int]:
    r = await get_redis()
    val = await r.get(rsk(cid))
    return int(val) if val else None


async def clear_reply_state(cid: int) -> None:
    r = await get_redis()
    await r.delete(rsk(cid))


async def set_state(cid: int, st: str) -> None:
    r = await get_redis()
    await r.set(sk(cid), st, ex=3600)


async def get_state(cid: int) -> Optional[str]:
    r = await get_redis()
    return await r.get(sk(cid))


async def clear_state(cid: int) -> None:
    r = await get_redis()
    await r.delete(sk(cid))


async def save_file_data(cid: int, data: dict) -> None:
    r = await get_redis()
    await r.set(fk(cid), json.dumps(data), ex=86400)


async def get_file_data(cid: int) -> Optional[dict]:
    r = await get_redis()
    val = await r.get(fk(cid))
    return json.loads(val) if val else None


async def clear_file_data(cid: int) -> None:
    r = await get_redis()
    await r.delete(fk(cid))


async def get_user_voice(cid: int) -> str:
    r = await get_redis()
    return await r.get(f"settings:{cid}:voice") or "en_us_001"


async def set_user_voice(cid: int, voice: str) -> None:
    r = await get_redis()
    await r.set(f"settings:{cid}:voice", voice)


async def get_user_system(cid: int) -> str:
    r = await get_redis()
    return await r.get(f"settings:{cid}:system") or ""


async def set_user_system(cid: int, text: str) -> None:
    r = await get_redis()
    await r.set(f"settings:{cid}:system", text)


async def clear_user_system(cid: int) -> None:
    r = await get_redis()
    await r.delete(f"settings:{cid}:system")


async def get_user_model(cid: int) -> str:
    r = await get_redis()
    return await r.get(f"settings:{cid}:model") or "gemini-2.5-flash-lite"


async def set_user_model(cid: int, model: str) -> None:
    r = await get_redis()
    await r.set(f"settings:{cid}:model", model)


async def get_user_temp(cid: int) -> float:
    r = await get_redis()
    val = await r.get(f"settings:{cid}:temp")
    return float(val) if val else 0.7


async def set_user_temp(cid: int, temp: float) -> None:
    r = await get_redis()
    await r.set(f"settings:{cid}:temp", str(temp))


async def ensure_user(cid: int, name: str) -> None:
    if not await user_exists(cid):
        await save_user(cid, name)


def is_admin(uid: int) -> bool:
    from config import ADMINS
    return uid in ADMINS


async def check_banned(cid: int) -> bool:
    banned = await is_banned(cid)
    admin = is_admin(cid)
    return banned and not admin


async def get_credit_message() -> str:
    r = await get_redis()
    return await r.get("settings:credit_message") or "Developer: Mero Team\nCredits: Thanks for using Mero AI Assistant Bot."


async def set_credit_message(text: str) -> None:
    r = await get_redis()
    await r.set("settings:credit_message", text)
