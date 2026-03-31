import httpx
from typing import Optional
from config import TELEGRAM_API, BOT_TOKEN


async def send_message(cid: int, text: str, parse_mode: Optional[str] = None, reply_markup: Optional[dict] = None) -> Optional[dict]:
    chunks = [text[i:i + 4096] for i in range(0, len(text), 4096)]
    result = None
    async with httpx.AsyncClient(timeout=30.0) as client:
        for chunk in chunks:
            payload: dict = {"chat_id": cid, "text": chunk}
            if parse_mode:
                payload["parse_mode"] = parse_mode
            if reply_markup:
                payload["reply_markup"] = reply_markup
            resp = await client.post(f"{TELEGRAM_API}/sendMessage", json=payload)
            result = resp.json()
            if not result.get("ok") and parse_mode:
                payload.pop("parse_mode", None)
                resp = await client.post(f"{TELEGRAM_API}/sendMessage", json=payload)
                result = resp.json()
    return result


async def send_photo(cid: int, photo_url: str, caption: Optional[str] = None, reply_markup: Optional[dict] = None) -> dict:
    payload: dict = {"chat_id": cid, "photo": photo_url}
    if caption:
        payload["caption"] = caption[:1024]
    if reply_markup:
        payload["reply_markup"] = reply_markup
    async with httpx.AsyncClient(timeout=60.0) as client:
        return (await client.post(f"{TELEGRAM_API}/sendPhoto", json=payload)).json()


async def send_voice_bytes(cid: int, audio_bytes: bytes, caption: Optional[str] = None, filename: str = "response.ogg", mime_type: str = "audio/ogg") -> dict:
    async with httpx.AsyncClient(timeout=60.0) as client:
        files = {"voice": (filename, audio_bytes, mime_type)}
        data: dict = {"chat_id": str(cid)}
        if caption:
            data["caption"] = caption[:1024]
        return (await client.post(f"{TELEGRAM_API}/sendVoice", files=files, data=data)).json()


async def download_telegram_file(file_id: str) -> Optional[bytes]:
    async with httpx.AsyncClient(timeout=60.0) as client:
        info = (await client.get(f"{TELEGRAM_API}/getFile?file_id={file_id}")).json()
        if not info.get("ok"):
            return None
        resp = await client.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{info['result']['file_path']}")
        return resp.content if resp.status_code == 200 else None


async def get_telegram_file_info(file_id: str) -> Optional[dict]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        info = (await client.get(f"{TELEGRAM_API}/getFile?file_id={file_id}")).json()
        if info.get("ok"):
            return info["result"]
    return None


async def answer_callback(cb_id: str, text: str = "") -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(f"{TELEGRAM_API}/answerCallbackQuery", json={"callback_query_id": cb_id, "text": text})


async def edit_message(cid: int, mid: int, text: str, parse_mode: Optional[str] = None, reply_markup: Optional[dict] = None) -> None:
    payload: dict = {"chat_id": cid, "message_id": mid, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup:
        payload["reply_markup"] = reply_markup
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(f"{TELEGRAM_API}/editMessageText", json=payload)
        if not resp.json().get("ok") and parse_mode:
            payload.pop("parse_mode", None)
            await client.post(f"{TELEGRAM_API}/editMessageText", json=payload)


async def delete_message(cid: int, mid: int) -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(f"{TELEGRAM_API}/deleteMessage", json={"chat_id": cid, "message_id": mid})


async def send_chat_action(cid: int, action: str = "typing") -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(f"{TELEGRAM_API}/sendChatAction", json={"chat_id": cid, "action": action})


async def send_document_bytes(cid: int, file_bytes: bytes, filename: str, caption: Optional[str] = None) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        files = {"document": (filename, file_bytes, "text/plain")}
        data: dict = {"chat_id": str(cid)}
        if caption:
            data["caption"] = caption[:1024]
        return (await client.post(f"{TELEGRAM_API}/sendDocument", files=files, data=data)).json()