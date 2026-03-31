import re


def escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _inline_format(text: str) -> str:
    text = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*\*(.+?)\*\*\*", r"<b><i>\1</i></b>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"__(.+?)__", r"<u>\1</u>", text)
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


def markdown_to_html(text: str) -> str:
    code_block_pattern = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)
    parts = []
    last_end = 0

    for match in code_block_pattern.finditer(text):
        before = text[last_end:match.start()]
        if before:
            parts.append(("text", before))
        lang = match.group(1)
        code = match.group(2)
        parts.append(("code", lang, code))
        last_end = match.end()

    remaining = text[last_end:]
    if remaining:
        parts.append(("text", remaining))

    result_parts = []
    for part in parts:
        if part[0] == "code":
            lang = part[1]
            code_content = part[2].rstrip("\n")
            escaped_code = escape_html(code_content)
            if lang:
                result_parts.append(f"<pre><code class=\"language-{escape_html(lang)}\">{escaped_code}</code></pre>")
            else:
                result_parts.append(f"<pre>{escaped_code}</pre>")
        else:
            raw_text = part[1]
            lines = raw_text.split("\n")
            processed_lines = []
            for line in lines:
                heading_match = re.match(r"^(#{1,6})\s+(.*)", line)
                if heading_match:
                    content = heading_match.group(2)
                    escaped = escape_html(content)
                    formatted = _inline_format(escaped)
                    processed_lines.append(f"\n<b>{formatted}</b>")
                    continue

                escaped_line = escape_html(line)
                formatted_line = _inline_format(escaped_line)
                processed_lines.append(formatted_line)

            result_parts.append("\n".join(processed_lines))

    return "".join(result_parts)