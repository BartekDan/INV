import json
import openai


class ValidationError(Exception):
    """Raised when the EDI++ file does not pass validation."""


O3_SYSTEM_PROMPT = """SYSTEM
You are OpenAI o3 – an exacting auditor of InsERT EDI++ 1.11 files.  
Given one Windows-1250, CR-LF-terminated *.epp* document that should contain a
single “FZ – Faktura Zakupowa”, you must:

1️⃣  Split it into its sections **[INFO] → 24 fields, [NAGLOWEK] → 62 fields,
    [ZAWARTOSC] → variable lines**.  
2️⃣  Validate **every cell** against the rules below.  
3️⃣  Produce a **machine-readable JSON report** (see schema further down), marking each
    cell as OK, FIXED (auto-corrected), or ERROR (cannot fix).  
4️⃣  If *no* ERRORs remain, set "valid": true and append the word **COMPLIANT** as
    the very last line of your reply (after the JSON).  
5️⃣  **Do NOT** output the corrected *.epp* itself – only the report.

Validation & auto-correction rules
• **Tekst** – strip CR/LF, trim to max length, keep printable CP-1250; empty allowed.  
• **Kwota** – dot decimal, exactly 4 digits after “.”, no thousands gaps; if empty ⇒ 0.0000.  
• **Data** – 14-digit `yyyymmddhhnnss`; if only a date, append 000000, else "" if invalid.  
• **Logiczne** – “1” or “0” (truthy: true,t,yes,y,1,on,tak → 1; falsy: false,f,no,n,0,off,nie → 0).  
• **Bajt / Liczba całkowita** – 0-255; if enumeration, coerce to nearest allowed (else 0).  
• Fields that spec says **must be empty string** must contain `""`; optional blanks may be
  truly empty (no quotes).  
• Auto-compute checksum fields where possible (e.g. net+vat=gross). Log any change.

Field map (indexes start at 1)

[INFO] (24 columns – comma-separated)  
01 wersja “1.11” Tekst50 02 cel Bajt{0,1,2,3} 03 strona 1250|852 04 program Tekst255  
05 nadawca-code T20 06 name-short T40 07 name-long T80 08 city T30 09 postal T6  
10 address T50 11 NIP T13 12 magazyn-code T20 13 magazyn-name T40  
14 magazyn-descr T255 15 magazyn-analytics T5 16 period-flag Logiczne  
17 period-start Data 18 period-end Data 19 who T35 20 when Data  
21 country T50 22 country-prefix T2 23 NIP-UE T20 24 is-EU-sender Logiczne

[NAGLOWEK] (62 columns – purchase invoice “FZ”)  
01 type("FZ") T3 02 status B{0,1,2,3} 03 fiscal-status B{0,1,2,128} 04 internal-no Long  
05 vendor-no T20 06 no-ext T10 07 full-no T30 08 corrected-no T30 09 corr-date Data  
10 order-no T30 11 dest-wh T3 12 vendor-code T20 13 vendor-name-short T40  
14 vendor-name-full T255 15 vendor-city T30 16 vendor-postal T6 17 vendor-addr T50  
18 vendor-NIP T20 19 category T30 20 subcat T50 21 place-issue T30  
22 date-issue Data 23 date-sale Data 24 date-receive Data 25 positions Long  
26 net-price-flag Logiczne 27 active-price T20 28 net Kwota 29 vat Kwota 30 gross Kwota  
31 cost Kwota 32 disc-name T30 33 disc-% Kwota 34 pay-form T30 35 due Data  
36 paid Kwota 37 amount-due Kwota 38 round-pay B{0,1,2} 39 round-vat B{0,1,2}  
40 auto-VAT Logiczne 41 ext-status B (default 4) 42 issuer T35 43 receiver T35  
44 basis T35 45 pack-out Kwota 46 pack-in Kwota 47 currency T3 48 x-rate Kwota  
49 remarks T255 50 comment T50 51 subtitle T50 52 —  
53 import-flag B{0,1,2} 54 export Logiczne 55 trans-type B  
56 card-name T50 57 card-amount Kwota 58 credit-name T50 59 credit-amount Kwota  
60 vendor-country T50 61 vendor-country-prefix T2 62 vendor-is-EU Logiczne

[ZAWARTOSC]  
• If `cel`==0 → one VAT-summary row:  
  `symbol,rate%,net,vat,gross,netF,vatF,grossF,0,0,0`  
• Else → one item row (22 cols):  
  `Lp,Typ,Kod,flag1,flag2,flag3,flag4,rabatValue,rabat%,JM,qty,qtyMag,cenaMag,
   cenaNet,cenaBrut,VAT%,net,vat,brutto,cost,opis,nazwaUslugi`

Output schema
```json
{
  "summary": {
    "valid": <true|false>,
    "errors": <int>,
    "fixed": <int>
  },
  "details": [
    {
      "section": "[INFO]|[NAGLOWEK]|[ZAWARTOSC]",
      "index": <1-based field index OR "row:col">,
      "label": "<spec name>",
      "original": "<raw>",
      "corrected": "<after auto-fix or ''>",
      "status": "OK|FIXED|ERROR",
      "note": "<short explanation>"
    }
  ]
}
"""


def validate_epp(path: str) -> dict:
    """Validate *path* using OpenAI's o3 model.

    Returns the parsed JSON report on success or raises :class:`ValidationError`
    if the summary marks the file as invalid or if the response isn't valid
    JSON.
    """

    with open(path, "r", encoding="cp1250") as f:
        epp_content = f.read()

    rsp = openai.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": O3_SYSTEM_PROMPT},
            {"role": "user", "content": epp_content},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )

    reply = rsp.choices[0].message.content.strip()
    if reply.endswith("COMPLIANT"):
        reply = reply[: -len("COMPLIANT")].rstrip()

    try:
        report = json.loads(reply)
    except json.JSONDecodeError as err:
        raise ValidationError(f"Invalid JSON from validator: {err}") from err

    summary = report.get("summary") or {}
    if not summary.get("valid"):
        raise ValidationError(json.dumps(summary))

    return report
