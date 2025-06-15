from __future__ import annotations
import time
from datetime import datetime
from pathlib import Path

from json_to_epp import agent2_json_to_epp

ROOT = Path(__file__).resolve().parent
WATCH_DIR = ROOT / "invoices_json"
OUTPUT_DIR = ROOT / "epp_output"

# ensure output directory exists
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def log(msg: str) -> None:
    ts = datetime.now().isoformat(timespec="seconds")
    print(f"{ts}  {msg}")


def convert(js_path: Path) -> None:
    epp_path = OUTPUT_DIR / js_path.with_suffix(".epp").name
    agent2_json_to_epp(str(js_path), str(epp_path))
    log(f"converted {js_path.name} -> {epp_path.relative_to(OUTPUT_DIR)}")


def watch() -> None:
    seen: dict[Path, float] = {}
    while True:
        for js in WATCH_DIR.glob("*.json"):
            mtime = js.stat().st_mtime
            if seen.get(js) != mtime:
                seen[js] = mtime
                try:
                    convert(js)
                except Exception as exc:
                    log(f"error processing {js.name}: {exc}")
        time.sleep(5)


if __name__ == "__main__":
    log("simple agent started")
    watch()
