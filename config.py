import os

BOT_TOKEN = "8655216165:AAEoDExRbxAmZVxGL9H0na4hziBEv6I-0RA"
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
POOL_API = "https://sr-pool-api-5bm.pages.dev"
MODEL = "gemini-2.5-flash-lite"
ADMINS = [7026190306, 6280547580]
TTS_API = "https://tik-tok-tts-s-m-ripon.vercel.app"
DEFAULT_VOICE = "en_us_001"
REDIS_URL = os.environ.get("REDIS_URL", "")
MAX_HISTORY = 30
CONTEXT_SIZE = 30

SHARE_TEXT = "🚀 Check out Mero AI Assistant — your free, fast & powerful AI companion on Telegram!\n\nhttps://t.me/meroaiassistantbot_bot"

AGENT_PROMPT = """Analyze the user prompt.
Return the exact functions only in python.
functions and intensions.
sendNormalMessage(query).
Sends normal message. The last query is already stored in my query variable.
sendYouTube(prompt, url).
These are not stored in my variables. So, extract prompt and url from user prompt and pass to the function properly. use this function if user gives YouTube link and prompt.
generateImage(query).
The last query is already stored in my query variable.
Understand the user prompt and pass functions properly.
Never write anything else except function.
User prompt: {user_prompt}"""

TEMPLATE_PROMPTS = [
    "Explain quantum computing simply",
    "Write a Python web scraper",
    "Summarize the latest AI news",
    "Translate 'hello' to 10 languages",
    "Solve: integral of x²·sin(x) dx",
    "Generate a business plan outline",
    "Explain blockchain in 3 sentences",
    "Write a poem about the ocean",
    "Compare React vs Vue vs Angular",
    "Tips for learning a new language",
]

SUPPORTED_MIME_TYPES = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.ms-excel": "xls",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/vnd.ms-powerpoint": "ppt",
    "text/plain": "txt",
    "text/csv": "csv",
    "text/html": "html",
    "text/css": "css",
    "text/javascript": "js",
    "application/json": "json",
    "application/xml": "xml",
    "text/xml": "xml",
    "text/x-python": "py",
    "text/x-java-source": "java",
    "text/x-c": "c",
    "text/x-c++": "cpp",
    "text/x-csharp": "cs",
    "text/x-go": "go",
    "text/x-rust": "rs",
    "text/x-ruby": "rb",
    "text/x-php": "php",
    "text/x-swift": "swift",
    "text/x-kotlin": "kt",
    "text/x-scala": "scala",
    "text/x-shellscript": "sh",
    "text/x-sql": "sql",
    "text/x-yaml": "yaml",
    "text/x-toml": "toml",
    "text/markdown": "md",
    "text/x-typescript": "ts",
    "text/x-lua": "lua",
    "text/x-perl": "pl",
    "text/x-r": "r",
    "text/x-dart": "dart",
    "application/x-httpd-php": "php",
    "application/javascript": "js",
    "application/typescript": "ts",
    "application/x-yaml": "yaml",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/ogg": "ogg",
    "audio/wav": "wav",
    "audio/webm": "webm",
    "audio/x-wav": "wav",
    "audio/flac": "flac",
    "audio/aac": "aac",
    "video/mp4": "mp4",
    "video/webm": "webm",
    "video/quicktime": "mov",
    "video/x-msvideo": "avi",
    "video/x-matroska": "mkv",
    "video/3gpp": "3gp",
}

CODE_EXTENSIONS = {
    "py", "js", "ts", "java", "c", "cpp", "cs", "go", "rs", "rb", "php",
    "swift", "kt", "scala", "sh", "sql", "yaml", "yml", "toml", "md",
    "html", "css", "json", "xml", "lua", "pl", "r", "dart", "jsx", "tsx",
    "vue", "svelte", "zig", "nim", "ex", "exs", "clj", "hs", "ml", "fs",
    "v", "d", "pas", "bas", "asm", "s", "coffee", "elm", "erl", "groovy",
    "tf", "dockerfile", "makefile", "cmake", "gradle", "bat", "ps1",
    "ini", "cfg", "conf", "env", "gitignore", "editorconfig", "txt",
    "csv", "tsv", "log", "diff", "patch",
}
