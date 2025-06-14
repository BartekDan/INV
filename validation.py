"""
validation.py – LLM validator + patch helper (full-script regeneration)
"""

from __future__ import annotations
import json
import pathlib
import re
import traceback
from textwrap import dedent
from typing import Dict, Any

from openai import OpenAI

MODEL = "o4-mini"
SCRIPT_VERSIONS_DIR = pathlib.Path("script_versions")
SCRIPT_VERSIONS_DIR.mkdir(exist_ok=True)

# ──────────────────────────────────────────────────────────────────────────
# FULL_SPEC – paste your entire SYSTEM #3 block here, verbatim (no edits)
# ──────────────────────────────────────────────────────────────────────────
FULL_SPEC = r"""
SYSTEM #3 – Full EDI ++ EPP v 1.11 specification (+ empirical rules)
────────────────────────────────────────────────────────────────────────
📂 FILE LAYOUT
  [INFO]  – single row, 24 comma-delimited columns
  [NAGLOWEK] – one row per invoice header, 62 columns
  [ZAWARTOSC] – one VAT-summary row (18 cols) for cel = 0
  File must finish with a trailing blank line.

🧾 DATA-TYPE RULES (apply to every column unless noted)
  • TekstX    → trim CR/LF, collapse >X chars, CP-1250 printable only.
  • Data      → yyyymmddhhnnss; if only date supplied, append 000000.
  • Kwota     → fixed-point “######.dddd” (4 decimals), dot as separator.
  • Logiczne  → accept (true,t,yes,y,1,on,tak) ⇒ 1; (false,f,no,n,0,off,nie) ⇒ 0.
  • Bajt/Int  → 0-255; if enum, coerce to nearest allowed else 0.
  • **Reserved** fields must always contain their defined value; if a field has no value, it must be encoded as an empty string literal ("").
  • If the field is "non-empty" or "always value" use reason to propose a value using other values that fits the field and meets data type requirements. 

═══════════════════════════════════════════════════════════════════════
[INFO] – 24 columns
Idx | Name (Type/Len) | Rule
────┼─────────────────┼─────────────────────────────────────────────────
01  wersja           T50 | **must = "1.11"**
02  cel              B   | {0=biuro,1=akwizytor,2=centrala,3=inny}
03  strona           Int | {852,1250}
04  program          T255| non-empty
05  nadawca-code     T20 | **reserved → ""**
06  name-short       T40 | non-empty
07  name-long        T80 | non-empty
08  city             T30 | non-empty
09  postal           T6  | non-empty  (PL "dd-ddd")
10  address          T50 | non-empty
11  NIP              T13 | non-empty (digits or "xxx-xxx-xx-xx")
12  magazyn-code     T20 | non-empty
13  magazyn-name     T40 | non-empty
14  magazyn-descr    T255| **reserved → ""**
15  magazyn-analyticsT5  | **reserved / optional blank**
16  period-flag      L   | 0/1
17  period-start     Data| if period-flag=0 → ""
18  period-end       Data| mirror rule to 17
19  who              T35 | non-empty
20  when             Data| non-empty
21  country          T50 | non-empty
22  country-prefix   T2  | "PL" for Poland else ISO-2
23  NIP-UE           T20 | **optional blank**
24  is-EU-sender     L   | 0/1

═══════════════════════════════════════════════════════════════════════
[NAGŁÓWEK] – 62 columns (cost invoice “FZ”);
Idx | Name / Type                | Rule snapshot
───┼───────────────────────────┼────────────────────────────────────────
01 | type           T3           | **must = "FZ"**
02 | status         B            | {0,1,2,3}   – always value
03 | fiscal-status  B            | {0,1,2,128} – always value
04 | internal-no    Long         | always value
05 | vendor-no      T20          | always value
06 | no-ext         T10          | **reserved → ""**
07 | full-no        T30          | always value
08 | corrected-no   T30          | optional (value / blank)
09 | corr-date      Data         | optional
10 | order-no       T30          | **blankable**
11 | dest-wh        T3           | **blankable**
12 | vendor-code    T20          | always value
13 | vendor-name-short T40       | always value
14 | vendor-name-full  T255      | always value
15 | vendor-city    T30          | always value
16 | vendor-postal  T6           | optional (value / "")
17 | vendor-addr    T50          | always value
18 | vendor-NIP     T20          | always value
19 | category       T30          | always value
20 | subcat         T50          | always value
21 | place-issue    T30          | always value
22 | date-issue     Data         | always value
23 | date-sale      Data         | always value
24 | date-receive   Data         | always value
25 | positions      Long         | always value
26 | net-price-flag L            | always value
27 | active-price   T20          | always value
28 | net            Kwota        | always value
29 | vat            Kwota        | always value
30 | gross          Kwota        | always value
31 | cost           Kwota        | always value
32 | disc-name      T30          | always value
33 | disc-%         Kwota        | always value
34 | pay-form       T30          | always value
35 | due            Data         | always value
36 | paid           Kwota        | always value
37 | amount-due     Kwota        | always value
38 | round-pay      B {0,1,2}    | always value
39 | round-vat      B {0,1,2}    | always value
40 | auto-VAT       L            | always value
41 | ext-status     B            | always value
42 | issuer         T35          | always value
43 | receiver       T35          | always value
44 | basis          T35          | always value
45 | pack-out       Kwota        | always value
46 | pack-in        Kwota        | always value
47 | currency       T3           | always value
48 | x-rate         Kwota        | always value
49 | remarks        T255         | optional
50 | comment        T50          | **reserved → ""**
51 | subtitle       T50          | **reserved → ""**
52 | (reserved)     –            | **blankable**
53 | import-flag    B            | always value
54 | export         L            | always value
55 | trans-type     B            | always value
56 | card-name      T50          | **reserved → ""**
57 | card-amount    Kwota        | always value
58 | credit-name    T50          | **reserved → ""**
59 | credit-amount  Kwota        | always value
60 | vendor-country T50          | **reserved → ""**
61 | vendor-country-prefix T2    | **reserved → ""**
62 | vendor-is-EU   L            | always value

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

! NEVER CHANGE VALUES OF FIELDS THAT ALREDY HAVE THEM UNLESS THE TYPE IS WRONG. 

Remember: return exactly one JSON object following SYSTEM #3; if no ERRORs,
set "valid": true and append the token COMPLIANT as the very last line.
List every error in json with reasononing. Don't just list general statistics. 
"""

# ──────────────────────────────────────────────────────────────────────────
# SCHEMA – require full script every time
# ──────────────────────────────────────────────────────────────────────────
SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "valid":  {"type": "boolean"},
        "errors": {"type": "array",   "items": {"type": "object"}},
        "report":    {"type": "object"},
        "reasoning": {"type": "string"},
        "new_script": {"type": "string", "minLength": 1},
    },
    "required": ["valid", "errors", "report", "reasoning", "new_script"],
}

# ──────────────────────────────────────────────────────────────────────────
def call_llm(epp_text: str) -> Dict[str, Any]:
    """Simple validation – no diff returned here."""
    client = OpenAI()
    messages = [
        {"role": "system", "content": "You are an EDI++ 1.11 validator; output JSON."},
        {"role": "system", "content": json.dumps(SCHEMA)},
        {"role": "system", "content": FULL_SPEC},
        {"role": "user", "content": f"---BEGIN:EPP---\n{epp_text}\n---END:EPP---"},
    ]
    # Print the entire prompt for debugging purposes
    print("call_llm messages:", json.dumps(messages, indent=2))
    rsp = client.chat.completions.create(
        model=MODEL,
        response_format={"type": "json_object"},
        temperature=1,
        reasoning_effort="high",
        messages=messages,
    )
    return json.loads(rsp.choices[0].message.content)

def validate_epp(path: str) -> Dict[str, Any]:
    """File-based entry point for pure validation (no script regeneration)."""
    try:
        txt = pathlib.Path(path).read_text("windows-1250")
        return call_llm(txt)
    except Exception:
        return {
            "valid": False,
            "errors": [{"message": "validator crash", "trace": traceback.format_exc()}],
        }

# ──────────────────────────────────────────────────────────────────────────
def analyze_epp(epp_text: str, script_code: str) -> Dict[str, Any]:
    """
    One-shot validation + full-script proposal.
    Returns JSON with keys:
      • report     – validation result
      • reasoning  – human explanation
      • new_script – full updated json_to_epp.py code
    """
    client = OpenAI()
    prompt = (
        "Check this EPP if it meets schema defined in System#3; if invalid return JSON with keys 'report', 'reasoning', "
        "'new_script'. List every invalid field in 'errors'. "
        "**The returned 'new_script' must be a _complete_ Python module and** "
        "**MUST define exactly** `def agent2_json_to_epp(json_path, output_path):` "
        "**with the same signature and behavior as in the original converter**. "
        "'new_script' should not include any other top-level functions. "
        "It should import only standard libraries and OpenAI helpers.\n"
        "List every invalid field in 'errors'. Do NOT just list general statistics. "
        "**You must never alter or invent any data from the input JSON** — invoice names, amounts, dates, everything must be preserved exactly. "
        "'new_script' must be a complete Python converter that, when used, fixes only formatting or structural bugs and reproduces the original data values unchanged.\n"
        "---BEGIN:EPP---\n" + epp_text + "\n---END:EPP---\n"
        "---BEGIN:SCRIPT---\n" + script_code + "\n---END:SCRIPT---"
    )
    messages = [
        {"role": "system", "content": "You are an EDI++ expert; follow schema."},
        {"role": "system", "content": json.dumps(SCHEMA)},
        {"role": "system", "content": FULL_SPEC},
        {"role": "user", "content": prompt},
    ]
    # Print the entire prompt for debugging purposes
    print("analyze_epp messages:", json.dumps(messages, indent=2))
    rsp = client.chat.completions.create(
        model=MODEL,
        response_format={"type": "json_object"},
        temperature=1,
        reasoning_effort="high",
        messages=messages,
    )
    return json.loads(rsp.choices[0].message.content)
