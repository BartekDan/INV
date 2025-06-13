"""
agent.py – JSON ➜ EDI++ self-healing agent (full-script regeneration)
Each retry asks the LLM for a complete new converter, writes it out,
and retries the failed invoice up to MAX_ITER times.
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
from validation import analyze_epp  # now returns 'new_script' instead of 'diff'

# ─── Folders & constants ──────────────────────────────────────────────
ROOT         = Path(__file__).resolve().parent
WATCH_DIR    = ROOT / "invoices_json"
OUTPUT_DIR   = ROOT / "epp_output"
REPAIRED_DIR = ROOT / "epp_repaired"
ARCHIVE_DIR  = ROOT / "epp_archive"
VERSIONS_DIR = ROOT / "script_versions"
ORIGINAL_CNV = ROOT / "json_to_epp.py"

MAX_ITER = 3
LOG_FILE = ROOT / "logs" / "agent.log"
LOG_FILE.parent.mkdir(exist_ok=True)

# ─── Logging helper ────────────────────────────────────────────────────
def log(msg: str) -> None:
    ts = datetime.now().isoformat(timespec="seconds")
    line = f"{ts}  {msg}"
    print(line)
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")

# ─── JSON-dump helper ───────────────────────────────────────────────────
def save_json(obj: Dict[str, Any] | str, path: Path) -> None:
    path.parent.mkdir(exist_ok=True)
    txt = obj if isinstance(obj, str) else json.dumps(obj, indent=2, ensure_ascii=False)
    path.write_text(txt, encoding="utf-8")

# ─── Versioned converter path ───────────────────────────────────────────
def version_path(n: int) -> Path:
    VERSIONS_DIR.mkdir(exist_ok=True)
    return VERSIONS_DIR / f"json_to_epp_v{n}.py"

# ─── Dynamic import helper ─────────────────────────────────────────────
def import_converter(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod

# ─── Process one invoice JSON ──────────────────────────────────────────
def process_file(json_file: Path) -> None:
    base = json_file.stem
    tmp_epp = OUTPUT_DIR / f"{base}.epp"

    # Ensure initial converter copy v0 exists
    v = 0
    cur_cnv = version_path(v)
    if not cur_cnv.exists():
        shutil.copy2(ORIGINAL_CNV, cur_cnv)

    for attempt in range(1, MAX_ITER + 1):
        mod_name = f"json_to_epp_v{v}"
        try:
            conv = import_converter(cur_cnv, mod_name)
        except Exception as exc:
            log(f"💥 import failed for {cur_cnv.name}: {exc!r}")
            break  # cannot proceed

        log(f"Attempt {attempt}/{MAX_ITER} – using {cur_cnv.name} at {cur_cnv.resolve()}")

        # 1️⃣  Convert JSON → EPP
        try:
            conv.agent2_json_to_epp(json_file, tmp_epp)
        except Exception as exc:
            log(f"💥 converter crashed: {exc!r}")
            break  # go archive

        # 2️⃣  Validate & ask for full updated script
        epp_txt = tmp_epp.read_text(encoding="cp1250", errors="ignore")
        result  = analyze_epp(epp_txt, cur_cnv.read_text(encoding="utf-8"))
        report      = result.get("report", {})
        reasoning   = result.get("reasoning", "")
        new_script  = result.get("new_script", "")

        save_json(report,    ROOT / "logs" / f"{base}_validation_{attempt}.json")
        save_json(reasoning, ROOT / "logs" / f"{base}_reasoning_{attempt}.txt")

        # ✅ Success?  Archive and return
        if report.get("valid"):
            REPAIRED_DIR.mkdir(exist_ok=True)
            shutil.move(tmp_epp, REPAIRED_DIR / tmp_epp.name)
            log(f"✅ invoice valid; output → {REPAIRED_DIR / tmp_epp.name}")
            return

        # No new script?  Stop retrying.
        if not new_script.strip():
            log("⚠️ LLM provided no new_script; stopping retries")
            break

        # 3️⃣  Write out the full new converter
        v += 1
        nxt = version_path(v)
        nxt.write_text(new_script, encoding="utf-8")
        cur_cnv = nxt  # use this for the next iteration

    # ▪️ All attempts exhausted or fatal error → archive the EPP
    ARCHIVE_DIR.mkdir(exist_ok=True)
    if tmp_epp.exists():
        shutil.move(tmp_epp, ARCHIVE_DIR / f"{base}_failed.epp")
    log(f"🗄️  archived {base}.epp after {attempt} attempt(s)")

# ─── Watch loop ────────────────────────────────────────────────────────
def watch() -> None:
    seen: Dict[Path, float] = {}
    WATCH_DIR.mkdir(exist_ok=True); OUTPUT_DIR.mkdir(exist_ok=True)
    while True:
        for js in WATCH_DIR.glob("*.json"):
            mtime = js.stat().st_mtime
            if seen.get(js) != mtime:
                seen[js] = mtime
                try:
                    process_file(js)
                except Exception as exc:
                    log(f"🚨 unhandled error on {js.name}: {exc!r}")
        time.sleep(5)

# ─── Entry point ───────────────────────────────────────────────────────
if __name__ == "__main__":
    load_api_key()
    log("agent started")
    watch()
