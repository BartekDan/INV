"""
agent.py – JSON \u279c EDI++ “self‑healing” agent
Re‑written 2025‑06‑12 to:
• create a full *new* json_to_epp_vN.py each iteration
• print the converter’s name & path on every run
• no .patch files are left behind
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

from openai_config import load_api_key
from validation import analyze_epp, apply_diff_to_script          # :contentReference[oaicite:4]{index=4}

# --------------------------------------------------------------------------- #
# Folders & constants
# --------------------------------------------------------------------------- #
ROOT           = Path(__file__).resolve().parent
WATCH_DIR      = ROOT / "invoices_json"
OUTPUT_DIR     = ROOT / "epp_output"
REPAIRED_DIR   = ROOT / "epp_repaired"
ARCHIVE_DIR    = ROOT / "epp_archive"
VERSIONS_DIR   = ROOT / "script_versions"
ORIGINAL_CONV  = ROOT / "json_to_epp.py"

MAX_ITER = 3                     # number of correction rounds per invoice
LOG_FILE = ROOT / "logs" / "agent.log"
LOG_FILE.parent.mkdir(exist_ok=True)

# --------------------------------------------------------------------------- #
# Utilities
# --------------------------------------------------------------------------- #
def log(msg: str) -> None:
    stamp = datetime.now().isoformat(timespec="seconds")
    line  = f"{stamp}  {msg}"
    print(line)
    LOG_FILE.write_text(LOG_FILE.read_text() + line + "\n" if LOG_FILE.exists() else line + "\n")


def save_json(obj: Dict[str, Any] | str, path: Path) -> Path:
    text = obj if isinstance(obj, str) else json.dumps(obj, indent=2, ensure_ascii=False)
    path.parent.mkdir(exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def version_file(n: int) -> Path:
    VERSIONS_DIR.mkdir(exist_ok=True)
    return VERSIONS_DIR / f"json_to_epp_v{n}.py"


def import_converter(path: Path, module_name: str):
    """Import converter at *path* under *module_name* and return the module."""
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)          # type: ignore[attr-defined]
    return module


# --------------------------------------------------------------------------- #
# Single‑file processing loop
# --------------------------------------------------------------------------- #
def process_file(json_path: Path) -> None:
    base        = json_path.stem
    tmp_epp     = OUTPUT_DIR / f"{base}.epp"

    # --- make sure v0 exists ------------------------------------------------
    v = 0
    current_conv = version_file(v)
    if not current_conv.exists():
        shutil.copy2(ORIGINAL_CONV, current_conv)

    for attempt in range(MAX_ITER):
        mod_name = f"json_to_epp_v{v}"
        conv_mod = import_converter(current_conv, mod_name)
        log(f"Attempt {attempt+1}/{MAX_ITER}: using {current_conv.name}  →  {current_conv.resolve()}")

        # 1⃣  Convert -------------------------------------------------------
        conv_mod.agent2_json_to_epp(json_path, tmp_epp)

        # 2⃣  Validate & maybe propose fix ----------------------------------
        epp_text = tmp_epp.read_text(encoding="cp1250", errors="ignore")
        result   = analyze_epp(epp_text, current_conv.read_text(encoding="utf-8"))
        report   = result.get("report", {})
        diff     = result.get("diff", "")
        reasoning= result.get("reasoning", "")

        save_json(report,    ROOT / "logs" / f"{base}_validation_{attempt}.json")
        save_json(reasoning, ROOT / "logs" / f"{base}_reasoning_{attempt}.txt")

        if report.get("valid"):
            REPAIRED_DIR.mkdir(exist_ok=True)
            shutil.move(tmp_epp, REPAIRED_DIR / tmp_epp.name)
            log(f"✅ success – invoice repaired with {current_conv.name}")
            return

        if not diff.strip():
            log("⚠️  LLM returned no diff – bailing out early")
            break

        # 3⃣  Build next full converter ------------------------------------
        v += 1
        next_conv = version_file(v)
        shutil.copy2(current_conv, next_conv)                # start from prev ver
        apply_diff_to_script(diff, next_conv)                # overwrite in‑place
        current_conv = next_conv                             # switch for next loop

    # ------------------------------------------------------------------- #
    # After MAX_ITER attempts -> archive
    # ------------------------------------------------------------------- #
    ARCHIVE_DIR.mkdir(exist_ok=True)
    shutil.move(tmp_epp, ARCHIVE_DIR / f"{base}_failed.epp")
    log(f"🗄️  archived {json_path.name} after {attempt+1} attempt(s)")


# --------------------------------------------------------------------------- #
# Watcher loop (simple polling)
# --------------------------------------------------------------------------- #
def watch() -> None:
    seen: Dict[Path, float] = {}
    WATCH_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)

    while True:
        for j in WATCH_DIR.glob("*.json"):
            mtime = j.stat().st_mtime
            if seen.get(j) != mtime:
                seen[j] = mtime
                try:
                    process_file(j)
                except Exception as exc:
                    log(f"🚨 Unhandled error on {j.name}: {exc!r}")
        time.sleep(5)


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    load_api_key()
    log("Self‑healing agent started")
    watch()
