import io
import json
import re
from html import escape, unescape
from typing import Literal

from pydantic import BaseModel, Field, ValidationError
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

from api import call_gemini_raw
from message import send_document_bytes, send_message


class ContentBlock(BaseModel):
    type: Literal["text", "paragraph", "color"]
    text: str = Field(min_length=1)
    color: str | None = None


class PdfPage(BaseModel):
    blocks: list[ContentBlock] = Field(default_factory=list)


class PdfDocument(BaseModel):
    pages: list[PdfPage] = Field(min_length=1)


_COLOR_FALLBACK = {
    "black": colors.black,
    "blue": colors.blue,
    "red": colors.red,
    "green": colors.green,
    "orange": colors.orange,
    "purple": colors.purple,
    "gray": colors.gray,
}


def _normalize_color(value: str | None) -> str:
    if not value:
        return "black"
    raw = value.strip().lower()
    if raw in _COLOR_FALLBACK:
        return raw
    if re.fullmatch(r"#(?:[0-9a-f]{3}|[0-9a-f]{6})", raw):
        return raw
    return "black"


def _extract_blocks(page_text: str) -> list[ContentBlock]:
    blocks: list[ContentBlock] = []
    tag_pattern = re.compile(
        r"<(?P<tag>text|paragraph|color)(?P<attrs>[^>]*)>(?P<body>.*?)</(?P=tag)>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    for match in tag_pattern.finditer(page_text):
        tag = match.group("tag").strip().lower()
        body = match.group("body").strip()
        if not body:
            continue
        if tag == "text":
            blocks.append(ContentBlock(type="text", text=body))
            continue
        if tag == "paragraph":
            blocks.append(ContentBlock(type="paragraph", text=body))
            continue

        attrs = match.group("attrs") or ""
        color_match = re.search(
            r'(?:name|value|code)\s*=\s*["\']([^"\']+)["\']',
            attrs,
            flags=re.IGNORECASE,
        )
        color_value = color_match.group(1) if color_match else "black"
        blocks.append(ContentBlock(type="color", text=body, color=_normalize_color(color_value)))

    if not blocks:
        stripped = re.sub(r"<[^>]+>", "", page_text).strip()
        if stripped:
            blocks.append(ContentBlock(type="paragraph", text=stripped))

    return blocks


def _prepare_markup(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""

    # Remove fenced wrappers commonly returned by models.
    text = re.sub(r"^\s*```(?:xml|html|markdown|md|text)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```\s*$", "", text)

    # Handle JSON wrappers like {"content":"<page>..."} or a quoted string with escaped \n.
    maybe_json = text.strip()
    if (maybe_json.startswith("{") and maybe_json.endswith("}")) or (maybe_json.startswith('"') and maybe_json.endswith('"')):
        try:
            decoded = json.loads(maybe_json)
            if isinstance(decoded, str):
                text = decoded
            elif isinstance(decoded, dict):
                for key in ("content", "text", "markup", "pdf", "response"):
                    if isinstance(decoded.get(key), str):
                        text = decoded[key]
                        break
        except Exception:
            pass

    text = unescape(text)
    text = text.replace("\\n", "\n").replace("\\t", "\t")
    return text.strip()


def parse_pdf_markup(markup: str) -> PdfDocument:
    cleaned_markup = _prepare_markup(markup)
    pages_raw = re.findall(r"<page>(.*?)</page>", cleaned_markup, flags=re.IGNORECASE | re.DOTALL)

    # Fallback: if model returns page-break tags but no <page> wrappers.
    if not pages_raw and cleaned_markup:
        chunks = re.split(r"<page-break\s*/?>", cleaned_markup, flags=re.IGNORECASE)
        pages_raw = [chunk for chunk in chunks if chunk.strip()]

    if not pages_raw and cleaned_markup:
        pages_raw = [cleaned_markup]
    if not pages_raw:
        raise ValueError("No content found in model output.")

    pages = [PdfPage(blocks=_extract_blocks(chunk)) for chunk in pages_raw]
    try:
        return PdfDocument(pages=pages)
    except ValidationError as exc:
        raise ValueError(f"Invalid PDF schema: {exc}") from exc


def render_pdf(doc: PdfDocument) -> bytes:
    buf = io.BytesIO()
    pdf = SimpleDocTemplate(buf, pagesize=A4, leftMargin=48, rightMargin=48, topMargin=48, bottomMargin=48)
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "MeroTitle",
        parent=styles["Heading2"],
        fontSize=16,
        leading=20,
        spaceAfter=10,
    )
    para_style = ParagraphStyle(
        "MeroParagraph",
        parent=styles["BodyText"],
        fontSize=11,
        leading=16,
        spaceAfter=8,
    )

    story = []
    for i, page in enumerate(doc.pages):
        if i > 0:
            story.append(PageBreak())

        for block in page.blocks:
            safe_text = escape(block.text).replace("\n", "<br/>")
            if block.type == "text":
                story.append(Paragraph(safe_text, title_style))
                story.append(Spacer(1, 4))
                continue

            if block.type == "color":
                color_value = _normalize_color(block.color)
                story.append(Paragraph(f'<font color="{color_value}">{safe_text}</font>', para_style))
                continue

            story.append(Paragraph(safe_text, para_style))

    pdf.build(story)
    return buf.getvalue()


async def execute_text_to_pdf(cid: int, prompt: str) -> None:
    await send_message(cid, "📄 Creating your PDF document...")

    system_text = (
        "If the user asks you about generating pdf from text, return texttopdf function with (prompt) parameter. "
        "with the following prompt. \n"
        '"Create text content to generate a pdf on ..... topic. Search the web and add requested pages. '
        "Return clean XML-like markup in this style:\n"
        "<page>\n<text>text</text>\n</page>\n<page>\n</page>\n"
        "Use only these tags: <page>, <text>, <paragraph>, <color>. "
        "Never return markdown fences, JSON, escaped tags, or explanations. "
        "Only return the content for pdf. "
        "Only return asked functions with specified parameter."
    )
    user_prompt = (
        "Create text content to generate a PDF. "
        f"Topic request: {prompt}. "
        "Search the web when needed, and return only <page>...</page> content with <text>, <paragraph>, and <color>."
    )

    raw = await call_gemini_raw([{"text": user_prompt}], system_text)
    if not raw:
        await send_message(cid, "❌ Failed to generate PDF content. Please try again.")
        return

    try:
        parsed = parse_pdf_markup(raw)
        pdf_bytes = render_pdf(parsed)
    except Exception:
        await send_message(cid, "❌ Couldn't parse PDF markup. Please refine your request and try again.")
        return

    await send_document_bytes(
        cid,
        pdf_bytes,
        "mero_document.pdf",
        "✅ Your PDF is ready.",
        mime_type="application/pdf",
    )
