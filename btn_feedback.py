from config import ADMINS
from message import send_message
from markdown_parse import escape_html


async def send_btn_feedback_to_admins(name: str, email: str, category: str, subject: str, message: str) -> bool:
    """Send formatted feedback from the /btn-feedback endpoint to all admins."""
    formatted_message = (
        f"Full Name: {name}. "
        f"Email: {email}. "
        f"Category: {category}. "
        f"Subject: {subject}. "
        f"Message: {message}"
    )
    
    for admin_id in ADMINS:
        try:
            await send_message(admin_id, formatted_message)
        except Exception:
            return False
    return True
