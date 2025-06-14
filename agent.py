# agent.py – three-stage loop per iteration

from __future__ import annotations
import importlib.util, json, shutil, time, ast
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

from openai_config import load_api_key
from validation import (
    step1_data_analysis,
    step2_apply_field_fixes,
    step3_fix_syntax,
)

# ────────────────────────────────────────────────────────────
# Paths & constants
# ────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
WATCH_DIR = ROOT / "invoices_json"
OUTPUT_DIR = ROOT / "epp_output"
REPAIRED_DIR = ROOT / "epp_repaired"
ARCHIVE_DIR = ROOT / "epp_archive"
VERSIONS_DIR = ROOT / "script_versions"
ORIGINAL_CNV = ROOT / "json_to_epp.py"
MAX_ITER = 3
LOG_FILE = ROOT / "logs" / "agent.log"

# Ensure dirs
LOG_FILE.parent.mkdir(exist_ok=True, parents=True)
for d in (WATCH_DIR, OUTPUT_DIR, VERSIONS_DIR, REPAIRED_DIR, ARCHIVE_DIR):
    d.mkdir(exist_ok=True, parents=True)


def log(msg: str) -> None:
    ts = datetime.now().isoformat(timespec="seconds")
    line = f"{ts}  {msg}"
    print(line)
    LOG_FILE.open("a", encoding="utf-8").write(line + "\n")


def save(path: Path, obj: Any) -> None:
    path.parent.mkdir(exist_ok=True, parents=True)
    txt = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=2)
    path.write_text(txt, encoding="utf-8")


def version_path(n: int) -> Path:
    return VERSIONS_DIR / f"json_to_epp_v{n}.py"


def import_converter(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore
    return mod


def process_file(js: Path) -> None:
    base = js.stem
    tmp_epp = OUTPUT_DIR / f"{base}.epp"
    json_text = js.read_text(encoding="utf-8")

    # 0️⃣ Seed v0 converter
    v = 0
    cur_cnv = version_path(v)
    if not cur_cnv.exists():
        shutil.copy2(ORIGINAL_CNV, cur_cnv)

    for attempt in range(1, MAX_ITER + 1):
        mod_name = f"json_to_epp_v{v}"

        # ─── IMPORT with syntax fix fallback (STEP 3) ─────────────
        try:
            conv = import_converter(cur_cnv, mod_name)
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            log(f"💥 import failed: {err}")
            fixed = step3_fix_syntax(cur_cnv.read_text("utf-8"), err)
            if not fixed.strip():
                log("⚠️ no syntax fix returned; aborting")
                break
            # write and retry once
            v += 1
            cur_cnv = version_path(v)
            cur_cnv.write_text(fixed, encoding="utf-8")
            log(f"🔧 syntax fixed; retrying import with {cur_cnv.name}")
            try:
                conv = import_converter(cur_cnv, f"json_to_epp_v{v}")
            except Exception as exc2:
                log(f"⚠️ reimport still failed: {exc2!r}")
                break

        log(f"Attempt {attempt}/{MAX_ITER} using {cur_cnv.name}")

        # ─── STEP 1: Convert JSON → EPP & Data Analysis ────────────
        try:
            conv.agent2_json_to_epp(js, tmp_epp)
        except Exception as exc:
            log(f"💥 conversion crash: {exc!r}")
            break

        epp_text = tmp_epp.read_text("cp1250", errors="ignore")
        field_report = step1_data_analysis(epp_text, json_text)
        save(ROOT / "logs" / f"{base}_step1_{attempt}.json", field_report)

        # If all fields OK → success
        if all(f["status"] == "OK" for f in field_report["fields"]):
            REPAIRED_DIR.mkdir(exist_ok=True)
            shutil.move(tmp_epp, REPAIRED_DIR / tmp_epp.name)
            log(f"✅ valid on data check, no code changes needed")
            return

        # ─── STEP 2: Apply Data Fixes to JSON ─────────────────────
        json_text = step2_apply_field_fixes(json_text, field_report)
        save(ROOT / "logs" / f"{base}_step2_{attempt}.json", json_text)
        js.write_text(json_text, encoding="utf-8")
        log(f"🔄 JSON updated; will retry conversion in next iteration")

        # loop back for next iteration (STEP 1 will run again)
        continue

    # ─── Exhausted or aborted → archive failed EPP ─────────────
    if tmp_epp.exists():
        ARCHIVE_DIR.mkdir(exist_ok=True)
        shutil.move(tmp_epp, ARCHIVE_DIR / f"{base}_failed.epp")
    log(f"🗄️ archived {base} after {attempt} attempt(s)")


def watch() -> None:
    seen: Dict[Path, float] = {}
    while True:
        for js in WATCH_DIR.glob("*.json"):
            m = js.stat().st_mtime
            if seen.get(js) != m:
                seen[js] = m
                try:
                    process_file(js)
                except Exception as exc:
                    log(f"🚨 unhandled error on {js.name}: {exc!r}")
        time.sleep(5)


if __name__ == "__main__":
    load_api_key()
    log("agent started")
    watch()
