"""Settings are read from the environment on every call so tests can override them."""
import os


def get(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def model() -> str:
    return get("CLAUDE_MODEL", "claude-haiku-5-5")


def api_key() -> str:
    return get("ANTHROPIC_API_KEY")


def demo_mode() -> bool:
    forced = get("DEMO_MODE").lower() in ("1", "true", "yes")
    return forced or not api_key()


def app_api_key() -> str:
    return get("APP_API_KEY")


def db_path() -> str:
    return get("DB_PATH", "docs.db")


def upload_dir() -> str:
    return get("UPLOAD_DIR", "uploads")


def max_upload_bytes() -> int:
    return int(float(get("MAX_UPLOAD_MB", "10")) * 1024 * 1024)


def top_k() -> int:
    return max(1, int(get("TOP_K", "5")))
