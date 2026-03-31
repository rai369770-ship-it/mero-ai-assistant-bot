import json
import redis
from typing import Optional
from config import REDIS_URL, MAX_HISTORY

r = redis.from_url(REDIS_URL, decode_responses=True)


def hk(cid: int) -> str:
    return f"chat:{cid}:history"


def rsk(cid: int) -> str:
    return f"chat:{cid}:reply_state"


def sk(cid: int) -> str:
    return f"chat:{cid}:state"


def fk(cid: int) -> str:
    return f"chat:{cid}:file"


def save_user(uid: int, name: str) -> None:
    r.hset("totalUsers", str(uid), name)


def user_exists(uid: int) -> bool:
    return r.hexists("totalUsers", str(uid))


def remove_all_user_data(uid: int) -> None:
    r.delete(hk(uid), rsk(uid), sk(uid), fk(uid))
    r.delete(f"settings:{uid}:system", f"settings:{uid}:voice", f"settings:{uid}:temp", f"settings:{uid}:model")
    r.hdel("totalUsers", str(uid))


def get_all_users() -> dict[str, str]:
    return r.hgetall("totalUsers")


def ban_user(uid: int, name: str) -> None:
    r.hset("bannedUsers", str(uid), name)


def unban_user(uid: int) -> None:
    r.hdel("bannedUsers", str(uid))


def is_banned(uid: int) -> bool:
    return r.hexists("bannedUsers", str(uid))


def get_banned_users() -> dict[str, str]:
    return r.hgetall("bannedUsers")


def save_message(cid: int, role: str, text: str) -> None:
    key = hk(cid)
    if r.llen(key) >= MAX_HISTORY * 2:
        r.ltrim(key, -((MAX_HISTORY - 1) * 2), -1)
    r.rpush(key, json.dumps({"role": role, "text": text}))


def get_all_history(cid: int) -> list[dict]:
    return [json.loads(i) for i in r.lrange(hk(cid), 0, -1)]


def get_recent_history(cid: int, count: int) -> list[dict]:
    key = hk(cid)
    total = r.llen(key)
    if total == 0:
        return []
    start = max(0, total - count * 2)
    return [json.loads(i) for i in r.lrange(key, start, -1)]


def clear_history(cid: int) -> None:
    r.delete(hk(cid))


def set_reply_state(cid: int, target: int) -> None:
    r.set(rsk(cid), str(target), ex=3600)


def get_reply_state(cid: int) -> Optional[int]:
    val = r.get(rsk(cid))
    return int(val) if val else None


def clear_reply_state(cid: int) -> None:
    r.delete(rsk(cid))


def set_state(cid: int, st: str) -> None:
    r.set(sk(cid), st, ex=3600)


def get_state(cid: int) -> Optional[str]:
    return r.get(sk(cid))


def clear_state(cid: int) -> None:
    r.delete(sk(cid))


def save_file_data(cid: int, data: dict) -> None:
    r.set(fk(cid), json.dumps(data), ex=86400)


def get_file_data(cid: int) -> Optional[dict]:
    val = r.get(fk(cid))
    return json.loads(val) if val else None


def clear_file_data(cid: int) -> None:
    r.delete(fk(cid))


def get_user_voice(cid: int) -> str:
    return r.get(f"settings:{cid}:voice") or "en_us_001"


def set_user_voice(cid: int, voice: str) -> None:
    r.set(f"settings:{cid}:voice", voice)


def get_user_system(cid: int) -> str:
    return r.get(f"settings:{cid}:system") or ""


def set_user_system(cid: int, text: str) -> None:
    r.set(f"settings:{cid}:system", text)


def clear_user_system(cid: int) -> None:
    r.delete(f"settings:{cid}:system")


def get_user_temp(cid: int) -> float:
    val = r.get(f"settings:{cid}:temp")
    return float(val) if val else 0.7


def set_user_temp(cid: int, temp: float) -> None:
    r.set(f"settings:{cid}:temp", str(temp))



def get_user_model(cid: int) -> str:
    return r.get(f"settings:{cid}:model") or "gemini-2.5-flash-lite"


def set_user_model(cid: int, model: str) -> None:
    r.set(f"settings:{cid}:model", model)

def ensure_user(cid: int, name: str) -> None:
    if not user_exists(cid):
        save_user(cid, name)


def is_admin(uid: int) -> bool:
    from config import ADMINS
    return uid in ADMINS


def check_banned(cid: int) -> bool:
    return is_banned(cid) and not is_admin(cid)