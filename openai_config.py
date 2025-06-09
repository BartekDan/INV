import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - handled via requirements
    load_dotenv = None


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
