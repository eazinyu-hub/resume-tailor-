"""Load a small, explicit backend-only .env file without exposing its values."""

import os
from pathlib import Path


BACKEND_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
ALLOWED_LOCAL_KEYS = {"DEEPSEEK_API_KEY", "DEEPSEEK_MODEL", "DATA_DIR", "CORS_ORIGINS"}
MAX_ENV_BYTES = 64 * 1024


class LocalConfigError(ValueError):
    pass


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def load_local_env(path: Path = BACKEND_ENV_PATH) -> str | None:
    """Load allow-listed values; real process variables always win."""
    if not path.exists():
        return None
    try:
        if path.stat().st_size > MAX_ENV_BYTES:
            raise LocalConfigError("后端 .env 超过 64 KB，请检查文件内容")
        for line_number, original in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            line = original.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                raise LocalConfigError(f"后端 .env 第 {line_number} 行缺少等号")
            key, value = (part.strip() for part in line.split("=", 1))
            if key not in ALLOWED_LOCAL_KEYS:
                continue
            os.environ.setdefault(key, _unquote(value))
        return None
    except (OSError, UnicodeError, LocalConfigError) as error:
        return str(error)
