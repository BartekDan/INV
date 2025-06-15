# validation.py – four-stage EPP self-healing workflow

from __future__ import annotations
import json
import pathlib
import traceback
from typing import Dict, Any
from openai import OpenAI

MODEL = "o4-mini"
SCRIPT_VERSIONS_DIR = pathlib.Path("script_versions")
SCRIPT_VERSIONS_DIR.mkdir(exist_ok=True)


# ────────────────────────────────────────────────────────────
# FULL_SPEC – paste your entire SYSTEM #3 block here, verbatim
# ────────────────────────────────────────────────────────────
FULL_SPEC = r"""
SYSTEM #3 – Full EDI ++ EPP v 1.11 specification (+ empirical rules)
────────────────────────────────────────────────────────────────────────
📂 FILE LAYOUT
  [INFO]  – single row, 24 comma-delimited columns
  [NAGLOWEK] – one row per invoice header, 62 columns
  [ZAWARTOSC] – one VAT-summary row (18 cols) for cel = 0
  Indexes start at 0. 
  File must finish with a trailing blank line.

🧾 DATA-TYPE RULES (apply to every column unless noted)
  • TekstX    → trim CR/LF, collapse >X chars, CP-1250 printable only.
  • Data      → yyyymmddhhnnss; if only date supplied, append 000000.
  • Kwota     → fixed-point “######.dddd” (4 decimals), dot as separator.
  • Logiczne  → accept (true,t,yes,y,1,on,tak) ⇒ 1; (false,f,no,n,0,off,nie) ⇒ 0.
  • Bajt/Int  → 0-255; if enum, coerce to nearest allowed else 0.
  • **Reserved** fields must always contain their defined value; if a field has no value, it must be encoded as an empty string literal ('""').
  • If the field is "non-empty" or "always value" and ONLY IF IT IS empty use reason to propose a value using other values that fits the field and meets data type requirements. 
  • Mark a field as INVALID onlty if it doesn't comply with data rules, but if it's not empty and data type is OK don't mark it as INVALID
  

═══════════════════════════════════════════════════════════════════════
[INFO] – 24 columns
Idx | Name (Type/Len) | Rule
────┼─────────────────┼─────────────────────────────────────────────────
00  wersja           T50 | **must = "1.11"**
01  cel              B   | {0=biuro,1=akwizytor,2=centrala,3=inny}
02  strona           Int | {852,1250}
03  program          T255| non-empty
04  nadawca-code     T20 | **reserved → '""'**
05  name-short       T40 | non-empty if empty  → '""'  
06  name-long        T80 | non-empty 
07  city             T30 | non-empty
08  postal           T6  | non-empty  (PL "dd-ddd")
09  address          T50 | non-empty
10  NIP              T13 | non-empty (digits or "xxx-xxx-xx-xx")
11  magazyn-code     T20 | non-empty  if empty  → '""'  
12  magazyn-name     T40 | non-empty  if empty  → '""'   
13  magazyn-descr    T255| **reserved → '""'**
14  magazyn-analyticsT5  | **reserved / optional blank**
15  period-flag      L   | 0/1
16  period-start     Data| if period-flag=0 → ""
17  period-end       Data| mirror rule to 17
18  who              T35 | non-empty  if empty  → '""'  
19  when             Data| non-empty  if empty put now
20  country          T50 | non-empty 
21  country-prefix   T2  | "PL" for Poland else ISO-2
22  NIP-UE           T20 | **optional blank**
23  is-EU-sender     L   | 0/1

═══════════════════════════════════════════════════════════════════════
[NAGŁÓWEK] – 62 columns (cost invoice “FZ”);
Idx | Name / Type                | Rule snapshot
───┼───────────────────────────┼────────────────────────────────────────
00 | type           T3           | **must = "FZ"**
01 | status         B            | {0,1,2,3}   – always value
02 | fiscal-status  B            | {0,1,2,128} – always value
03 | internal-no    Long         | always value if empty put 0000
04 | vendor-no      T20          | always value  if empty  → '""' 
05 | no-ext         T10          | **reserved → ""**
06 | full-no        T30          | always value  
07 | corrected-no   T30          | optional (value / blank)
08 | corr-date      Data         | optional 
09 | order-no       T30          | **blankable**
10 | dest-wh        T3           | **blankable**
11 | supplier-code  T20          | always value if empty  → '""' 
12 | supplier-name-short T40     | always value if empty  → '""'  
13 | supplier-name-full  T255    | always value
14 | supplier-city    T30        | always value
15 | supplier-postal  T6         | optional (value / "")
16 | supplier-addr    T50        | always value 
17 | supplier-NIP     T20        | always value
18 | category       T30          | always value  if empty  → '""' 
19 | subcat         T50          | always value if empty  → '""' 
20 | place-issue    T30          | always value if empty  → '""' 
21 | date-issue     Data         | always value 
22 | date-sale      Data         | optional if empty leave blank
23 | date-receive   Data         | optional if empty leave blank
24 | positions      Long         | always value
25 | net-price-flag L            | always value if empty put 1
26 | active-price   T20          | always value  if empty  → '""' 
27 | net            Kwota        | always value
28 | vat            Kwota        | always value
29 | gross          Kwota        | always value
30 | cost           Kwota        | always value  if empty put gross
31 | disc-name      T30          | always value if empty  → '""' 
32 | disc-%         Kwota        | always value  if empty put 0
33 | pay-form       T30          | always value if empty  → '""' 
34 | due            Data         | always value  
35 | paid           Kwota        | always value  if empty put 0 
36 | amount-due     Kwota        | always value if mepty put gross
37 | round-pay      B {0,1,2}    | always value 
38 | round-vat      B {0,1,2}    | always value
39 | auto-VAT       L            | always value 
40 | ext-status     B            | always value
41 | issuer         T35          | always value  if empty  → '""' 
42 | receiver       T35          | always value  if empty  → '""' 
43 | basis          T35          | always value  
44 | pack-out       Kwota        | always value  if empty put 0 
45 | pack-in        Kwota        | always value  if empty put 0 
46 | currency       T3           | always value 
47 | x-rate         Kwota        | always value
48 | remarks        T255         | optional if empty  → '""' 
49 | comment        T50          | **reserved → ""**
50 | subtitle       T50          | **reserved → ""**
51 | (reserved)     –            | **blankable**
52 | import-flag    B            | always value
53 | export         L            | always value
54 | trans-type     B            | always value
55 | card-name      T50          | **reserved → ""**
56 | card-amount    Kwota        | always value
57 | credit-name    T50          | **reserved → ""**
58 | credit-amount  Kwota        | always value
59 | vendor-country T50          | **reserved → ""**
60 | vendor-country-prefix T2    | **reserved → ""**
61 | vendor-is-EU   L            | always value

═══════════════════════════════════════════════════════════════════════
[ZAWARTOSC] – VAT-summary row (18 columns when cel = 0)
All 18 columns contained non-empty numeric values in the sample file,
therefore they are treated as **required values** for cel = 0.
(For cel ≠ 0, the 22-column item layout from the official PDF applies.)

═══════════════════════════════════════════════════════════════════════
ADDITIONAL CONSISTENCY CHECKS
• net + vat = gross (±0.0001)  ➜ if mismatch, auto-compute gross, mark FIXED.
• sum of VAT-summary rows must equal header vat/net/gross.
• positions (Hdr-25) must equal count of [ZAWARTOSC] rows.
• date_sale ≤ date_issue ≤ now.
• if vendor_is_EU = 1 → vendor_country_prefix ≠ "PL".

! NEVER CHANGE VALUES OF FIELDS THAT ALREDY HAVE THEM UNLESS THE TYPE IS WRONG. NEVE REASON ANOUT THEM. 

Remember: return exactly one JSON object following SYSTEM #3; if no ERRORs,
set "valid": true and append the token COMPLIANT as the very last line.
List every error in json with reasononing. Don't just list general statistics. 
"""

# ────────────────────────────────────────────────────────────
# SCHEMA for validate_only (Stage 0)
# ────────────────────────────────────────────────────────────
SCHEMA_VALIDATE: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "valid":  {"type": "boolean"},
        "errors": {"type": "array", "items": {"type": "object"}},
    },
    "required": ["valid", "errors"],
}

# ────────────────────────────────────────────────────────────
# SCHEMA for step1_data_analysis (Stage 1)
# ────────────────────────────────────────────────────────────
SCHEMA_STEP1: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "fields": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "segment":     {"type": "string"},
                    "idx":         {"type": "integer"},
                    "field":       {"type": "string"},
                    "status":      {"type": "string", "enum": ["OK","MISSING","INVALID"]},
                    "suggestion":  {"type": "string"},
                    "code_ref": {
                        "type": "object",
                        "properties": {
                            "var":       {"type": "string"},
                            "index":     {"type": "integer"},
                            "line_hint": {"type": "string"}
                        },
                        "required": ["var","index","line_hint"]
                    },
                },
                "required": ["segment","idx","field","status","suggestion","code_ref"]
            }
        }
    },
    "required": ["fields"],
}


def validate_only(epp_text: str) -> dict:
    """
    Stage 0: Pure validation of EPP against the spec.
    Returns {"valid":bool, "errors":[…]}.
    """
    client = OpenAI()
    rsp = client.chat.completions.create(
        model=MODEL,
        temperature=1,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "You are an EDI++ 1.11 validator; output JSON."},
            {"role": "system", "content": json.dumps(SCHEMA_VALIDATE)},
            {"role": "system", "content": FULL_SPEC},
            {"role": "user",   "content": f"---BEGIN:EPP---\n{epp_text}\n---END:EPP---"},
        ],
    )
    return json.loads(rsp.choices[0].message.content)


def step1_data_analysis(epp_text: str, json_text: str) -> dict:
    """
    Stage 1: Field-level analysis.
    Returns {"fields":[{segment,idx,field,status,suggestion,code_ref},…]}
    """
    client = OpenAI()
    messages = [
        {
            "role": "system",
            "content": (
                "You are an expert EDI++ data validator. Inspect the EPP output "
                "against the FULL_SPEC and the original JSON. For each field in "
                "[INFO], [NAGLOWEK], [ZAWARTOSC], output an object with:\n"
                "- segment (\"INFO\",\"NAGLOWEK\",\"ZAWARTOSC\")\n"
                "- idx (column number)\n"
                "- field (JSON key name)\n"
                "- status: \"OK\"/\"MISSING\"/\"INVALID\"\n"
                "- suggestion: what to fill (per spec) or \"\" if unknown\n"
                "- code_ref: {var:\"info\" or \"hdr\", index:<integer>, line_hint:<one-line code snippet>}\n"
                "Do NOT propose code – only structured JSON guidance."
            )
        },
        {"role": "system", "content": json.dumps(SCHEMA_STEP1)},
        {"role": "system", "content": FULL_SPEC},
        {
            "role": "user",
            "content": (
                "---BEGIN:JSON---\n" + json_text + "\n---END:JSON---\n\n"
                "---BEGIN:EPP---\n"  + epp_text  + "\n---END:EPP---"
            )
        },
    ]
    rsp = client.chat.completions.create(
        model=MODEL,
        temperature=1,
        response_format={"type": "json_object"},
        messages=messages,
    )
    return json.loads(rsp.choices[0].message.content)


def step2_patch_script(script_code: str, field_report: dict) -> str:
    """
    Stage 2: Surgical rewrite of converter code.
    Inject suggested values directly at code_ref locations.
    Returns the full corrected Python source.
    """
    client = OpenAI()
    prompt = (
        "You are a Python patch assistant. Given the field report below, "
        "modify the function agent2_json_to_epp() so that for each entry you "
        "locate the exact line matching code_ref.line_hint and replace the assignment "
        "with the suggestion. Preserve all other code and formatting, touching only "
        "those lines. Return ONLY the complete corrected Python source."
        "\n\nField report:\n"
        f"{json.dumps(field_report, ensure_ascii=False, indent=2)}\n\n"
        "Current converter code:\n```python\n"
        + script_code
        + "\n```"
    )
    rsp = client.chat.completions.create(
        model=MODEL,
        temperature=1,
        response_format={"type": "text"},
        messages=[
            {"role": "system", "content": "You are a Python syntax-aware patch assistant."},
            {"role": "user",   "content": prompt},
        ],
    )
    return rsp.choices[0].message.content or script_code


def step3_fix_syntax(script_code: str, error_msg: str) -> str:
    """
    Stage 3: If the patched script fails to import, fix only syntax errors.
    Returns corrected full source or empty on failure.
    """
    client = OpenAI()
    prompt = (
        f"The following Python module failed to parse with: {error_msg}\n"
        "Here is the source:\n```python\n" + script_code + "\n```\n\n"
        "Please return ONLY the corrected Python code, fixing syntax errors "
        "but making no other changes."
    )
    rsp = client.chat.completions.create(
        model=MODEL,
        temperature=1,
        response_format={"type": "text"},
        messages=[
            {"role": "system", "content": "You are a Python syntax fixer."},
            {"role": "user",   "content": prompt},
        ],
    )
    return rsp.choices[0].message.content or ""
