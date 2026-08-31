"""
Environment and configuration loader for Resume ATS Analyzer.
Loads environment variables from .env file or system environment with zero external dependencies.
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

def load_env():
    """Loads key-value pairs from .env file into os.environ if not already present."""
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if key and key not in os.environ:
                        os.environ[key] = val

load_env()

# Standardized portable cache directory (XDG compliant with project fallback)
def get_cache_dir() -> Path:
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache:
        cache_dir = Path(xdg_cache) / "resume_ats_analyzer"
    else:
        cache_dir = PROJECT_ROOT / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir

AFFINDA_API_KEY = os.environ.get("AFFINDA_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
