"""
agent.py – two-step self-healing loop
"""

from __future__ import annotations
import importlib.util
import json
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any
import ast

from openai_config import load_api_key
from validation import analyze_epp

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
    ts = datetime.now().isoformat(timespec="seconds")
    line = f"{ts}  {msg}"
    print(line)
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")

def save(path: Path, obj: Any) -> None:
    path.parent.mkdir(exist_ok=True)
    txt = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=2)
    path.write_text(txt, encoding="utf-8")

def version_path(n: int) -> Path:
    VERSIONS_DIR.mkdir(exist_ok=True)
    return VERSIONS_DIR / f"json_to_epp_v{n}.py"

def import_converter(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore
    return mod

def process_file(js: Path) -> None:
    base = js.stem
    tmp_epp = OUTPUT_DIR / f"{base}.epp"
    json_text = js.read_text(encoding="utf-8")

    # seed v0
    v = 0
    cur_cnv = version_path(0)
    if not cur_cnv.exists():
        shutil.copy2(ORIGINAL_CNV, cur_cnv)

    for attempt in range(1, MAX_ITER+1):
        mod_name = f"json_to_epp_v{v}"
        try:
            conv = import_converter(cur_cnv, mod_name)
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            log(f"💥 import failed: {err}")
            # Attempt syntax fix
            from validation import fix_syntax
            code = cur_cnv.read_text("utf-8")
            fixed = fix_syntax(code, err)
            if fixed.strip():
                # write out fixed version and retry import once
                v += 1
                nxt = version_path(v)
                nxt.write_text(fixed, encoding="utf-8")
                cur_cnv = nxt
                mod_name = f"json_to_epp_v{v}"
                log(f"🔧 syntax‐fixed converter; retrying with {cur_cnv.name}")
                try:
                    conv = import_converter(cur_cnv, mod_name)
                except Exception as exc2:
                    log(f"⚠️ reimport still failed: {exc2!r}")
                    break
            else:
                log("⚠️ no syntax fix returned; aborting")
                break

        log(f"Attempt {attempt}/{MAX_ITER} using {cur_cnv.name}")

        try:
            conv.agent2_json_to_epp(js, tmp_epp)
        except Exception as exc:
            log(f"💥 conversion crash: {exc!r}")
            break

        epp_text = tmp_epp.read_text(encoding="cp1250", errors="ignore")
        result = analyze_epp(epp_text, json_text, cur_cnv.read_text("utf-8"))

        report    = result["report"]
        reasoning = result["reasoning"]
        new_code  = result["new_script"]

        save(ROOT/"logs"/f"{base}_report_{attempt}.json", report)
        save(ROOT/"logs"/f"{base}_reasoning_{attempt}.txt", reasoning)

        if report.get("valid"):
            REPAIRED_DIR.mkdir(exist_ok=True)
            shutil.move(tmp_epp, REPAIRED_DIR/tmp_epp.name)
            log(f"✅ fixed on attempt {attempt}")
            return

        if not new_code.strip():
            log("⚠️ no new_script provided; stopping")
            break

        # syntax check + signature guard
        try:
            tree = ast.parse(new_code)
            assert "agent2_json_to_epp" in new_code
        except Exception as exc:
            log(f"⚠️ invalid script: {exc}")
            break

        # write next version
        v += 1
        nxt = version_path(v)
        nxt.write_text(new_code, encoding="utf-8")
        cur_cnv = nxt

    ARCHIVE_DIR.mkdir(exist_ok=True)
    if tmp_epp.exists():
        shutil.move(tmp_epp, ARCHIVE_DIR/f"{base}_failed.epp")
    log(f"🗄️ archived {base} after {attempt} attempts")

def watch() -> None:
    seen: Dict[Path, float] = {}
    WATCH_DIR.mkdir(exist_ok=True); OUTPUT_DIR.mkdir(exist_ok=True)
    while True:
        for js in WATCH_DIR.glob("*.json"):
            m = js.stat().st_mtime
            if seen.get(js) != m:
                seen[js] = m
                process_file(js)
        time.sleep(5)

if __name__ == "__main__":
    load_api_key()
    log("agent started")
    watch()
