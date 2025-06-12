"""
agent.py – JSON ➜ EDI++ self‑healing agent
------------------------------------------
• Watches invoices_json/ for *.json.
• Converts with json_to_epp_vN.py (new copy per iteration).
• Validates; on errors asks LLM for a patch.
• Saves each full converter in script_versions/.
• Logs converter file & absolute path every attempt.
"""

from __future__ import annotations

import importlib.util, json, shutil, time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

from openai_config import load_api_key
from validation import analyze_epp, apply_diff_to_script   # patched helper

# ─── folders ──────────────────────────────────────────────
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



def log(msg: str) -> None:
    ts   = datetime.now().isoformat(timespec="seconds")
    line = f"{ts}  {msg}"
    print(line)
    LOG_FILE.parent.mkdir(exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")



# ─── helpers ──────────────────────────────────────────────
def save_json(obj: Dict[str, Any] | str, path: Path) -> None:
    path.parent.mkdir(exist_ok=True)
    txt = obj if isinstance(obj, str) else json.dumps(obj, indent=2, ensure_ascii=False)
    path.write_text(txt, encoding="utf-8")


def version_path(n: int) -> Path:
    VERSIONS_DIR.mkdir(exist_ok=True)
    return VERSIONS_DIR / f"json_to_epp_v{n}.py"


def import_converter(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)        # type: ignore[attr-defined]
    return mod


# ─── core per‑file loop ──────────────────────────────────
def process_file(json_file: Path) -> None:
    base = json_file.stem
    tmp_epp = OUTPUT_DIR / f"{base}.epp"

    # make sure v0 exists
    v = 0
    cur_cnv = version_path(v)
    if not cur_cnv.exists():
        shutil.copy2(ORIGINAL_CNV, cur_cnv)

    for attempt in range(MAX_ITER):
        mod_name = f"json_to_epp_v{v}"
        conv = import_converter(cur_cnv, mod_name)
        log(f"Attempt {attempt+1}/{MAX_ITER}  –  using {cur_cnv.name} at {cur_cnv.resolve()}")

        # 1) convert -----------------------------------------------------------------
        try:
            conv.agent2_json_to_epp(json_file, tmp_epp)
        except Exception as crash:
            log(f"💥 converter crashed: {crash!r}")
            # Feed the crash text to LLM as a pseudo‑error so it can propose fix
            fail_report = {"valid": False, "errors": [{"message": f"converter crash: {crash}"}]}
            diff = ""
            reasoning = str(crash)
        else:
            # 2) validate ------------------------------------------------------------
            epp_txt = tmp_epp.read_text(encoding="cp1250", errors="ignore")
            result = analyze_epp(epp_txt, cur_cnv.read_text(encoding="utf-8"))
            fail_report = result.get("report", {})
            diff = result.get("diff", "")
            reasoning = result.get("reasoning", "")

        # store reports / reasoning
        save_json(fail_report, ROOT / "logs" / f"{base}_validation_{attempt}.json")
        save_json(reasoning,  ROOT / "logs" / f"{base}_reasoning_{attempt}.txt")

        if fail_report.get("valid"):
            REPAIRED_DIR.mkdir(exist_ok=True)
            shutil.move(tmp_epp, REPAIRED_DIR / tmp_epp.name)
            log(f"✅ fixed with {cur_cnv.name}")
            return

        if not diff.strip():
            log("⚠️  LLM provided no diff – stop retries")
            break

        # 3) build next full converter ---------------------------------------------
        v += 1
        nxt = version_path(v)
        shutil.copy2(cur_cnv, nxt)            # start from previous code
        apply_diff_to_script(diff, nxt)       # overwrite in place
        cur_cnv = nxt                         # switch
    # end for

    ARCHIVE_DIR.mkdir(exist_ok=True)
    shutil.move(tmp_epp, ARCHIVE_DIR / f"{base}_failed.epp")
    log(f"🗄️  gave up on {json_file.name} after {attempt+1} attempt(s)")


# ─── directory watcher (polling) ──────────────────────────
def watch() -> None:
    seen: Dict[Path, float] = {}
    WATCH_DIR.mkdir(exist_ok=True); OUTPUT_DIR.mkdir(exist_ok=True)
    while True:
        for js in WATCH_DIR.glob("*.json"):
            mt = js.stat().st_mtime
            if seen.get(js) != mt:
                seen[js] = mt
                try:
                    process_file(js)
                except Exception as ex:
                    log(f"🚨 unhandled error on {js.name}: {ex!r}")
        time.sleep(5)


if __name__ == "__main__":
    load_api_key()
    log("agent started")
    watch()
