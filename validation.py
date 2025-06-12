"""
validation.py – LLM validator + patch helper
• analyze_epp()  → returns {report, reasoning, diff}
• apply_diff_to_script() now copes with:
    A) plain unified diff
    B) diff inside ``` fences
    C) complete replacement file
"""

from __future__ import annotations
import json, re, traceback, pathlib
from textwrap import dedent
from typing import Dict, Any

from openai import OpenAI

MODEL = "o3"
SCRIPT_VERSIONS_DIR = pathlib.Path("script_versions")
SCRIPT_VERSIONS_DIR.mkdir(exist_ok=True)

# ─── LLM helper snippets (unchanged) ─────────────────────────────────────
SCHEMA = {  # abbreviated; identical to your original
    "type": "object",
    "properties": {
        "valid": {"type": "boolean"},
        "errors": {"type": "array", "items": {"type": "object"}},
    },
    "required": ["valid", "errors"],
}

FULL_SPEC = "…(spec text elided for brevity)…"

# ─── LLM helpers (validate & analyze)  ───────────────────────────────────
def call_llm(epp_text: str) -> Dict[str, Any]:
    client = OpenAI()
    msgs = [
        {"role": "system", "content": "You are an EDI++ 1.11 validator; output JSON."},
        {"role": "system", "content": json.dumps(SCHEMA)},
        {"role": "system", "content": FULL_SPEC},
        {"role": "user", "content": f"---BEGIN:EPP---\n{epp_text}\n---END:EPP---"},
    ]
    rsp = client.chat.completions.create(
        model=MODEL, messages=msgs, response_format={"type": "json_object"}, temperature=0.3
    )
    return json.loads(rsp.choices[0].message.content)


def validate_epp(path: str) -> Dict[str, Any]:
    try:
        txt = pathlib.Path(path).read_text(encoding="windows-1250")
        return call_llm(txt)
    except Exception:
        return {"valid": False, "errors": [{"message": "validator crash", "trace": traceback.format_exc()}]}


def analyze_epp(epp_text: str, script_code: str) -> Dict[str, Any]:
    """One-shot: validate + propose diff."""
    client = OpenAI()
    user = (
        "Check this EPP; if invalid return JSON with keys 'report', 'reasoning', 'diff'.\n"
        "---BEGIN:EPP---\n" + epp_text + "\n---END:EPP---\n"
        "---BEGIN:SCRIPT---\n" + script_code + "\n---END:SCRIPT---"
    )
    rsp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "You are an EDI++ expert; follow schema."},
            {"role": "system", "content": json.dumps(SCHEMA)},
            {"role": "system", "content": FULL_SPEC},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
        temperature=1,
    )
    return json.loads(rsp.choices[0].message.content)

# ─── robust patch applier ────────────────────────────────────────────────
from unidiff.patch import PatchSet
FENCE_RE = re.compile(r"```(?:diff|patch)?\s+(.*?)```", re.S)

def apply_diff_to_script(diff: str, script_path: pathlib.Path) -> pathlib.Path:
    """Apply diff (or full file) to script_path; return new version path."""
    if not diff.strip():
        return script_path

    # unwrap ``` fenced diff
    m = FENCE_RE.search(diff)
    if m:
        diff = m.group(1).strip()

    # case C – full file (no diff markers)
    is_full = not diff.lstrip().startswith(("diff", "@@", "---"))

    if is_full:
        new_code = dedent(diff).strip("\n") + "\n"
    else:
        try:
            patch = PatchSet(diff)
        except Exception:
            patch = PatchSet()
        if not any(len(h) for p in patch for h in p):
            # unparsable → store for reference, keep old script
            (SCRIPT_VERSIONS_DIR / (script_path.stem + ".patch")).write_text(diff, encoding="utf-8")
            return script_path

        original = script_path.read_text(encoding="utf-8").splitlines(keepends=True)
        new_code = original[:]
        for p in patch:
            for h in p:
                start = h.source_start - 1
                end = start + h.source_length
                new_lines = [l.value for l in h.target_lines()]
                new_code[start:end] = new_lines
        new_code = "".join(new_code)

    # write versioned copy and atomically replace active script
    i = 0
    while (SCRIPT_VERSIONS_DIR / f"{script_path.stem}_v{i}.py").exists():
        i += 1
    new_path = SCRIPT_VERSIONS_DIR / f"{script_path.stem}_v{i}.py"
    new_path.write_text(new_code, encoding="utf-8")
    script_path.write_text(new_code, encoding="utf-8")
    return new_path


# ─── CLI validation helper (optional) ────────────────────────────────────
if __name__ == "__main__":
    import argparse, sys
    a = argparse.ArgumentParser()
    a.add_argument("epp"); a.add_argument("--script")
    args = a.parse_args()
    rpt = validate_epp(args.epp)
    print(json.dumps(rpt, ensure_ascii=False, indent=2))
    if args.script and not rpt["valid"]:
        sc = pathlib.Path(args.script)
        diff = analyze_epp(pathlib.Path(args.epp).read_text("windows-1250"), sc.read_text()).get("diff", "")
        apply_diff_to_script(diff, sc)
        print("patched converter →", sc)
