import os
import json
from pathlib import Path
from datetime import datetime

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - handled via requirements
    load_dotenv = None


PROMPT_DIR = Path(__file__).resolve().parent / "logs" / "prompts"
PROMPT_DIR.mkdir(parents=True, exist_ok=True)


def load_api_key() -> None:
    """Load OPENAI_API_KEY from a ``.env`` file if present."""
    if load_dotenv is not None:
        env_path = Path(__file__).with_name('.env')
        if env_path.exists():
            load_dotenv(env_path)
    if not os.getenv("OPENAI_API_KEY"):
        # `openai` library will check this variable
        raise RuntimeError(
            "OPENAI_API_KEY not set. Create a .env file with OPENAI_API_KEY=<your key>"
        )


def record_prompt(messages: list[dict], prefix: str = "prompt") -> None:
    """Print *messages* and save them as JSON under ``logs/prompts``."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = PROMPT_DIR / f"{prefix}_{ts}.json"
    path.write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PROMPT:")
    print(json.dumps(messages, ensure_ascii=False, indent=2))
    print(f"Saved prompt to {path}")
