"""
agent.py – JSON \u279c EDI++ “self-healing” conversion agent
------------------------------------------------------

* Watches `invoices_json/` for *.json invoices.
* Converts them with json_to_epp.agent2_json_to_epp.
* Validates the `.epp`; on failure asks an LLM for a patch.
* Applies the patch to `json_to_epp.py`, reloads, and retries.
* Stops after MAX_ITER attempts (or sooner if the LLM has no fix).
"""

from __future__ import annotations

import importlib
import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

from openai_config import load_api_key
import json_to_epp  # will be hot-reloaded after every patch
from json_to_epp import agent2_json_to_epp  # re-bound after reload
from validation import analyze_epp, apply_diff_to_script     # exposes LLM & patch helper

# --------------------------------------------------------------------------- #
# Configuration – adjust paths to taste
# --------------------------------------------------------------------------- #
WATCH_DIR     = Path("invoices_json")
OUTPUT_DIR    = Path("epp_output")
REPAIRED_DIR  = Path("epp_repaired")
ARCHIVE_DIR   = Path("epp_archive")
SCRIPT        = Path("json_to_epp.py")   # the converter we patch
LOG_DIR       = Path("logs")
SCRIPT_VERS   = Path("script_versions")

MAX_ITER = 3   # hard cap for attempts on a single file

# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def log(msg: str) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    with open(LOG_DIR / "agent.log", "a", encoding="utf-8") as fp:
        fp.write(f"{datetime.now().isoformat()}  {msg}\n")
    print(msg)


def load_script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _save(txt: str | Dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(txt if isinstance(txt, str) else json.dumps(txt, indent=2))
    return path


def save_validation_report(base: str, i: int, report: Dict[str, Any]) -> Path:
    return _save(report, LOG_DIR / f"{base}_validation_{i}.json")


def save_diff_patch(base: str, i: int, diff: str) -> Path:
    return _save(diff, LOG_DIR / f"{base}_diff_{i}.patch")


def save_reasoning(base: str, i: int, thoughts: str) -> Path:
    return _save(thoughts, LOG_DIR / f"{base}_reasoning_{i}.txt")


def backup_script(i: int) -> Path:
    SCRIPT_VERS.mkdir(exist_ok=True)
    dst = SCRIPT_VERS / f"{SCRIPT.name}_v{i}.bak"
    shutil.copy2(SCRIPT, dst)
    return dst


# --------------------------------------------------------------------------- #
# Core processing logic
# --------------------------------------------------------------------------- #
def process_file(json_file: Path) -> None:
    """
    Convert one JSON invoice \u279c validate \u279c (optionally) patch converter.
    """
    global agent2_json_to_epp   # we re-bind after hot-reload
    base        = json_file.stem
    tmp_epp     = OUTPUT_DIR / f"{base}.epp"

    for iteration in range(MAX_ITER):
        # \u0031\u20e3  Convert -------------------------------------------------------
        agent2_json_to_epp(json_file, tmp_epp)

        # \u0032\u20e3  Validate ------------------------------------------------------
        epp_content = tmp_epp.read_text(encoding="cp1250", errors="ignore")
        result      = analyze_epp(epp_content, load_script())   # LLM call
        report      = result.get("report", {})

        report_path = save_validation_report(base, iteration, report)

        # 2a. Success – move to repaired dir and exit
        if report.get("valid"):
            REPAIRED_DIR.mkdir(exist_ok=True)
            final_path = REPAIRED_DIR / tmp_epp.name
            shutil.move(tmp_epp, final_path)
            log(f"\u2705 {json_file.name} OK \u2192 {final_path}  (report \u2192 {report_path})")
            return

        # 2b. Failure – log details
        diff       = result.get("diff", "")
        reasoning  = result.get("reasoning", "")
        log(f"\u274c {json_file.name} failed (iteration {iteration})  \u2013 see {report_path}")
        save_diff_patch(base, iteration, diff)
        save_reasoning(base, iteration, reasoning)

        # \u0033\u20e3  Maybe patch the converter ------------------------------------
        if diff.strip():
            backup_script(iteration)
            apply_diff_to_script(diff, SCRIPT, iteration)       # writes new code

            # Hot-reload json_to_epp so the *next* iteration uses the patch
            importlib.reload(json_to_epp)
            agent2_json_to_epp = json_to_epp.agent2_json_to_epp
        else:
            log("\u26a0\ufe0f  LLM produced no diff; giving up early.")
            break   # nothing more we can do automatically

    # ------------------------------------------------------------------- #
    # If we drop out of the loop, we never produced a valid file
    # ------------------------------------------------------------------- #
    ARCHIVE_DIR.mkdir(exist_ok=True)
    shutil.move(tmp_epp, ARCHIVE_DIR / f"{base}_failed.epp")
    log(f"\U0001f5c4\ufe0f  {json_file.name} archived after {iteration + 1} attempt(s)")


# --------------------------------------------------------------------------- #
# Very small watch-loop (polling; simple but cross-platform & dependency-free)
# --------------------------------------------------------------------------- #
def watch_loop() -> None:
    log(f"Watching {WATCH_DIR.resolve()} for invoices \u2026")
    seen: Dict[Path, float] = {}
    WATCH_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)

    while True:
        for path in WATCH_DIR.glob("*.json"):
            mtime = path.stat().st_mtime
            if seen.get(path) != mtime:     # new or modified file
                time.sleep(1)               # debounce quick writes
                seen[path] = mtime
                try:
                    process_file(path)
                except Exception as exc:    # keep daemon alive
                    log(f"\ud83d\udea8 Unhandled error on {path.name}: {exc!r}")

        time.sleep(5)  # poll interval


# --------------------------------------------------------------------------- #
# Entry-point
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    load_api_key()
    log(f"Using json_to_epp at {json_to_epp.__file__}")
    watch_loop()
