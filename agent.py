import os
import time
import shutil
import subprocess
import json
from datetime import datetime

from openai_config import load_api_key

from json_to_epp import agent2_json_to_epp
from validation import validate_epp, ValidationError

WATCH_DIR = 'invoices_json'
OUTPUT_DIR = 'epp_output'
REPAIRED_DIR = 'epp_repaired'
ARCHIVE_DIR = 'epp_archive'
SCRIPT = 'json_to_epp.py'
SCRIPT_VERSIONS = 'script_versions'
LOG_DIR = 'logs'
MAX_ITER = 5


def log(msg):
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(os.path.join(LOG_DIR, 'agent.log'), 'a') as f:
        f.write(f"{datetime.now().isoformat()} {msg}\n")
    print(msg)


def load_script():
    with open(SCRIPT, 'r') as f:
        return f.read()


def save_script_version(iteration):
    os.makedirs(SCRIPT_VERSIONS, exist_ok=True)
    dst = os.path.join(SCRIPT_VERSIONS, f'{os.path.basename(SCRIPT)}_{iteration}')
    shutil.copy2(SCRIPT, dst)


def call_ai(epp_content, errors, script_content):
    import openai
    prompt = (
        "The following EDI++ file did not pass validation:\n" +
        epp_content +
        "\nErrors:" + str(errors) +
        "\nCurrent conversion script:\n" + script_content +
        "\nProvide a unified diff to fix the script."
    )
    response = openai.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are an AI assistant."},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
    )
    return response.choices[0].message.content


def apply_patch(diff_text):
    import unidiff
    from unidiff.patch import PatchSet
    patch = PatchSet(diff_text)
    with open(SCRIPT, 'r') as f:
        lines = f.readlines()
    for patched_file in patch:
        for hunk in patched_file:
            start = hunk.source_start - 1
            end = start + hunk.source_length
            new_lines = [l.value for l in hunk.target_lines()]
            lines[start:end] = new_lines
    with open(SCRIPT, 'w') as f:
        f.writelines(lines)


def process_file(json_file):
    base = os.path.splitext(os.path.basename(json_file))[0]
    tmp_epp = os.path.join(OUTPUT_DIR, base + '.epp')
    agent2_json_to_epp(json_file, tmp_epp)
    iter_no = 0
    while iter_no < MAX_ITER:
        try:
            validate_epp(tmp_epp)
            final_path = os.path.join(REPAIRED_DIR, os.path.basename(tmp_epp))
            shutil.move(tmp_epp, final_path)
            log(f"{json_file} converted successfully")
            return
        except ValidationError as e:
            # e contains the full JSON report from the validator
            try:
                report = json.loads(str(e))
                log(f"Validation failed: {report.get('summary')}")
            except json.JSONDecodeError:
                # fall back to raw message
                log(f"Validation failed: {e}")
            with open(tmp_epp, 'r', encoding='cp1250') as f:
                epp_content = f.read()
            script_content = load_script()
            # pass the raw JSON report to the AI for context
            diff = call_ai(epp_content, str(e), script_content)
            log(f"AI diff:\n{diff}")
            save_script_version(iter_no)
            apply_patch(diff)
            agent2_json_to_epp(json_file, tmp_epp)
            iter_no += 1
    shutil.move(tmp_epp, os.path.join(ARCHIVE_DIR, base + '_failed.epp'))
    log(f"Failed to convert {json_file} after {MAX_ITER} attempts")


def watch_loop():
    os.makedirs(WATCH_DIR, exist_ok=True)
    seen = {}
    while True:
        for fname in os.listdir(WATCH_DIR):
            if not fname.lower().endswith('.json'):
                continue
            path = os.path.join(WATCH_DIR, fname)
            mtime = os.path.getmtime(path)
            if path not in seen or seen[path] != mtime:
                time.sleep(1)  # debounce
                seen[path] = mtime
                process_file(path)
        time.sleep(5)


if __name__ == '__main__':
    load_api_key()
    watch_loop()
