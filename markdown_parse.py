import re


def escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _format_inline(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*\*(.+?)\*\*\*", r"<b><i>\1</i></b>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"__(.+?)__", r"<u>\1</u>", text)
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)
    return text


def _render_text_block(block: str) -> str:
    lines = block.split("\n")
    out = []
    in_ul = False
    in_ol = False
    for raw in lines:
        line = raw.rstrip()
        if not line:
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if in_ol:
                out.append("</ol>")
                in_ol = False
            out.append("")
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if in_ol:
                out.append("</ol>")
                in_ol = False
            content = _format_inline(escape_html(heading.group(2).strip()))
            out.append(f"<b>{content}</b>")
            continue
        unordered = re.match(r"^\s*[-*]\s+(.*)$", line)
        if unordered:
            if in_ol:
                out.append("</ol>")
                in_ol = False
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            content = _format_inline(escape_html(unordered.group(1).strip()))
            out.append(f"<li>{content}</li>")
            continue
        ordered = re.match(r"^\s*\d+[.)]\s+(.*)$", line)
        if ordered:
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if not in_ol:
                out.append("<ol>")
                in_ol = True
            content = _format_inline(escape_html(ordered.group(1).strip()))
            out.append(f"<li>{content}</li>")
            continue
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False
        quote = re.match(r"^>\s?(.*)$", line)
        if quote:
            content = _format_inline(escape_html(quote.group(1)))
            out.append(f"<blockquote>{content}</blockquote>")
            continue
        out.append(_format_inline(escape_html(line)))
    if in_ul:
        out.append("</ul>")
    if in_ol:
        out.append("</ol>")
    return "\n".join(out)


def markdown_to_html(text: str) -> str:
    pattern = re.compile(r"```([\w+-]*)\n(.*?)```", re.DOTALL)
    parts = []
    last = 0
    for match in pattern.finditer(text):
        before = text[last:match.start()]
        if before:
            parts.append(("text", before))
        parts.append(("code", match.group(1).strip(), match.group(2).rstrip("\n")))
        last = match.end()
    tail = text[last:]
    if tail:
        parts.append(("text", tail))
    if not parts:
        return _render_text_block(text)
    rendered = []
    for part in parts:
        if part[0] == "code":
            lang = escape_html(part[1])
            code = escape_html(part[2])
            if lang:
                rendered.append(f"<pre><code class=\"language-{lang}\">{code}</code></pre>")
            else:
                rendered.append(f"<pre>{code}</pre>")
        else:
            rendered.append(_render_text_block(part[1]))
    return "".join(rendered)
