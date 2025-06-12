import os
import time
import shutil
import json
from datetime import datetime
from pathlib import Path

from openai_config import load_api_key

import json_to_epp
from json_to_epp import agent2_json_to_epp
from validation import analyze_epp, apply_diff_to_script

WATCH_DIR = "invoices_json"
OUTPUT_DIR = "epp_output"
REPAIRED_DIR = "epp_repaired"
ARCHIVE_DIR = "epp_archive"
SCRIPT = "json_to_epp.py"
LOG_DIR = "logs"
MAX_ITER = 3


def log(msg):
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(os.path.join(LOG_DIR, "agent.log"), "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat()} {msg}\n")
    print(msg)


def load_script():
    with open(SCRIPT, "r") as f:
        return f.read()


def save_validation_report(base, iteration, report_str):
    os.makedirs(LOG_DIR, exist_ok=True)
    path = os.path.join(LOG_DIR, f"{base}_validation_{iteration}.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write(report_str)
    return path


def save_diff_patch(base, iteration, diff_text):
    os.makedirs(LOG_DIR, exist_ok=True)
    path = os.path.join(LOG_DIR, f"{base}_diff_{iteration}.patch")
    with open(path, "w", encoding="utf-8") as f:
        f.write(diff_text)
    return path


def save_reasoning(base, iteration, text):
    os.makedirs(LOG_DIR, exist_ok=True)
    path = os.path.join(LOG_DIR, f"{base}_reasoning_{iteration}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def backup_script(iteration: int) -> str:
    """Save the current converter script before applying a patch."""
    os.makedirs("script_versions", exist_ok=True)
    base = Path(SCRIPT).name
    dst = os.path.join("script_versions", f"{base}_{iteration}_orig")
    shutil.copy(SCRIPT, dst)
    return dst




def process_file(json_file):
    base = os.path.splitext(os.path.basename(json_file))[0]
    tmp_epp = os.path.join(OUTPUT_DIR, base + ".epp")
    global agent2_json_to_epp
    iter_no = 0
    while iter_no < MAX_ITER:
        agent2_json_to_epp(json_file, tmp_epp)
        with open(tmp_epp, "r", encoding="cp1250") as f:
            epp_content = f.read()
        script_content = load_script()
        result = analyze_epp(epp_content, script_content)
        report = result.get("report", {})
        report_path = save_validation_report(
            base, iter_no, json.dumps(report, indent=2)
        )
        if report.get("valid"):
            final_path = os.path.join(REPAIRED_DIR, os.path.basename(tmp_epp))
            shutil.move(tmp_epp, final_path)
            log(
                f"{json_file} converted successfully. Validation report saved to {report_path}"
            )
            return
        else:
            diff = result.get("diff", "")
            reasoning = result.get("reasoning", "")
            log(
                f"Validation failed: {report.get('errors')} (report saved to {report_path})"
            )
            diff_path = save_diff_patch(base, iter_no, diff)
            reasoning_path = save_reasoning(base, iter_no, reasoning)
            log(
                f"AI reasoning saved to {reasoning_path}\n{reasoning}\n"
                f"AI diff saved to {diff_path}\n{diff}"
            )
            if diff:
                backup_script(iter_no)
                apply_diff_to_script(diff, Path(SCRIPT), iter_no)
                import importlib
                importlib.reload(json_to_epp)
                agent2_json_to_epp = json_to_epp.agent2_json_to_epp
            iter_no += 1
    shutil.move(tmp_epp, os.path.join(ARCHIVE_DIR, base + "_failed.epp"))
    log(f"Failed to convert {json_file} after {MAX_ITER} attempts")


def watch_loop():
    os.makedirs(WATCH_DIR, exist_ok=True)
    seen = {}
    while True:
        for fname in os.listdir(WATCH_DIR):
            if not fname.lower().endswith(".json"):
                continue
            path = os.path.join(WATCH_DIR, fname)
            mtime = os.path.getmtime(path)
            if path not in seen or seen[path] != mtime:
                time.sleep(1)  # debounce
                seen[path] = mtime
                process_file(path)
        time.sleep(5)


if __name__ == "__main__":
    load_api_key()
    log(f"Using json_to_epp module at {json_to_epp.__file__}")
    watch_loop()
