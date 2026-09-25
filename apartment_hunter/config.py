"""Settings from .env and the environment. Credentials stay on the server side."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = Path(__file__).resolve().parent
DATA = PACKAGE / "data"
STATIC = PACKAGE / "static"


def load_env(path=None):
    """Read KEY=value lines. Existing environment variables win."""
    for candidate in [path] if path else [Path.cwd() / ".env", ROOT / ".env"]:
        if candidate and Path(candidate).exists():
            for line in Path(candidate).read_text().splitlines():
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
            return


def settings():
    env = os.environ.get
    home = Path(env("HUNTER_HOME", "~/.apartment-hunter")).expanduser()
    return {
        "typesafe_key": env("TYPESAFE_API_KEY", ""),
        "typesafe_model": env("TYPESAFE_MODEL", "jev-latest"),
        "text_key": env("TEXT_MODEL_API_KEY", ""),
        "text_base": env("TEXT_MODEL_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/"),
        "text_model": env("TEXT_MODEL", "inception/mercury-2.5"),
        "text_reasoning": env("TEXT_MODEL_REASONING", "none"),
        # The vision helper uses the OpenRouter key from jev-ultrafast unless a separate one is set.
        "vision_key": env("VISION_API_KEY") or env("TEXT_MODEL_API_KEY", ""),
        "vision_base": (env("VISION_BASE_URL") or env("TEXT_MODEL_BASE_URL") or "https://openrouter.ai/api/v1").rstrip("/"),
        "vision_model": env("VISION_MODEL", "google/gemini-2.5-flash-lite"),
        "chrome_mode": env("CHROME_MODE", "user"),
        "chrome_cdp_url": env("CHROME_CDP_URL", "http://127.0.0.1:9333"),
        "port": int(env("HUNTER_PORT", "8777")),
        "home": home,
    }
