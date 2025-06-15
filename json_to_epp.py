# ============================================================
# === 🆕  G-DRIVE BATCH HELPER  (MUST BE ABOVE YOUR CODE)  ===
# ============================================================
from pathlib import Path
OUTPUT_DIR = Path("/content/drive/MyDrive/inv/invoices/json")


def gdrive_batch_convert_json_to_epp(
    gdrive_src: str,
    dst_subfolder: str = "epps",
    mount_if_needed: bool = False,
):
    """Convert JSON invoice files on Google Drive to EDI++ (.epp)."""
    if mount_if_needed:
        try:
            from google.colab import drive

            drive.mount("/content/drive")
        except Exception:
            # silently ignore if not in Colab
            pass

    src_dir = Path(gdrive_src).expanduser()
    if not src_dir.is_dir():
        raise ValueError(f"{src_dir} is not a valid directory")

    dst_dir = src_dir / dst_subfolder
    dst_dir.mkdir(exist_ok=True)

    print(f"\U0001F4C2 Input : {src_dir}")
    print(f"\U0001F4C1 Output: {dst_dir}")
    print("\u2500" * 46)
    for json_path in src_dir.glob("*.json"):
        epp_path = dst_dir / json_path.with_suffix(".epp").name
        print(f"→ {json_path.name}  →  {epp_path.relative_to(src_dir)}")
        try:
            agent2_json_to_epp(json_path, epp_path)
            print("   ✅ done")
        except Exception as err:
            print(f"   ⚠️  skipped ({err})")
    print("🎉 Finished")


# ============================================================
# === 🆕  OPTIONAL LOCAL BATCH (NON-GDRIVE)  =================
# ============================================================
from pathlib import Path as _P


def batch_convert_json_to_epp(folder: str = "."):
    """Convert every *.json in *folder* to .epp beside it."""
    for json_path in _P(folder).glob("*.json"):
        epp_path = json_path.with_suffix(".epp")
        print(f"→ {json_path.name}  →  {epp_path.name}")
        try:
            agent2_json_to_epp(json_path, epp_path)
            print("   ✅ done")
        except Exception as err:
            print(f"   ⚠️  skipped ({err})")


# ============================================================
# === 🔧  POST-PROCESSING NORMALISER  ========================
# ============================================================
from decimal import Decimal, InvalidOperation
import re
import datetime as _dt


# --- primitive formatters -----------------------------------
def _fmt_money(raw: str) -> str:
    raw = (
        (raw or "")
        .replace(" ", "")
        .replace(",", ".")
        .strip()
    )
    if raw == "":
        return ""
    try:
        return f"{Decimal(raw):.4f}"
    except InvalidOperation:
        return raw


_date_only_re = re.compile(r"^(\d{4})[^\d]?(\d{2})[^\d]?(\d{2})$")
_dt14_re = re.compile(r"^\d{14}$")


def _fmt_date(raw: str) -> str:
    raw = (raw or "").strip()
    if raw == "" or _dt14_re.fullmatch(raw):
        return raw
    m = _date_only_re.match(raw)
    if m:
        y, m_, d = m.groups()
        return f"{y}{m_}{d}000000"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y%m%d%H%M%S"):
        try:
            return _dt.datetime.strptime(raw, fmt).strftime("%Y%m%d%H%M%S")
        except ValueError:
            pass
    return raw


# --- field maps ---------------------------------------------
_MONEY_IDX_HDR = {27, 28, 29, 30, 32, 35, 36, 56, 58}
_DATE_IDX_HDR = {21, 22, 23, 34}
_DATE_IDX_INFO = {16, 17}


def _normalise_numeric_and_dates(info: list[str], hdr: list[str], vats: list[list[str]]) -> None:
    """Normalise money and date fields in-place."""
    for i in _MONEY_IDX_HDR:
        hdr[i] = _fmt_money(hdr[i])
    for i in _DATE_IDX_HDR:
        hdr[i] = _fmt_date(hdr[i])
    for i in _DATE_IDX_INFO:
        info[i] = _fmt_date(info[i])
    for row in vats:
        for j in (2, 3, 4):
            row[j] = _fmt_money(row[j])


# ============================================================
# === 🔻🔻🔻  MAIN CONVERTER  🔻🔻🔻
# ============================================================
import json
import calendar


def s(val):
    """Convert any value to a safe string (empty if None)."""
    return "" if val is None else str(val)



def agent2_json_to_epp(json_path: str, epp_path: str):
    """Convert `json_path` invoice to EDI++ 1.11 file at `epp_path`."""
    meta = json.load(open(json_path, encoding="utf-8"))

    info = [""] * 24
    hdr: list[str] = [""] * 62
    r = [""] * 14

    info[0] = '"1.11"'
    info[1] = "0"
    info[2] = "1250"
    info[3] = '"RETRAI-IMPORT"'
    info[4] = '""'
    info[5] = f"\"{s(meta.get('buyer_short_name'))}\""
    info[6] = f"\"{s(meta.get('buyer_name'))}\""
    info[7] = f"\"{s(meta.get('buyer_city'))}\""
    info[8] = f"\"{s(meta.get('buyer_postal_zip_code'))}\""
    info[9] = f"\"{s(meta.get('byuer_address(street_and_number)'))}\""
    info[10] = f"\"{s(meta.get('byuer_nip'))}\""
    info[11] = '"1"'
    info[12] = '"Magazyn"'
    info[13] = '"Opis magazynu"'
    info[14] = '""'

    info[15] = "1"

    inv_date_raw = s(meta.get("invoice_date"))
    if inv_date_raw:
        if "-" in inv_date_raw:
            y, m = inv_date_raw.split("-")[:2]
        else:
            y, m = inv_date_raw[:4], inv_date_raw[4:6]
        try:
            y_int, m_int = int(y), int(m)
            first_of_month = f"{y}{m}01000000"
            last_day = calendar.monthrange(y_int, m_int)[1]
            last_of_month = f"{y}{m}{last_day:02d}235959"
            info[16] = first_of_month
            info[17] = last_of_month
        except ValueError:
            info[16] = info[17] = ""
    else:
        info[16] = info[17] = ""
    info[18] = '"Nadawca"'
    info[19] =  _dt.datetime.now().strftime("%Y%m%d%H%M%S")
    info[20] = f"\"{s(meta.get('buyer_country'))}\""
    info[21] = f"\"{s(meta.get('buyer_country_prefix'))}\""
    info[22] = ""
    info[23] = "1"

    hdr[0] = '"FZ"'
    hdr[1] = "1"
    hdr[2] = "0"
    hdr[3] = "0000000"
    hdr[4] = s(meta.get("invoice_number"))
    hdr[5] = ""
    hdr[6] = f"\"FZ {hdr[4]}\""
    hdr[7] = s(meta.get("inoice_number_of_document_being_correcterd"))
    hdr[8] = s(meta.get("data_of_document_being_corretcted"))
    hdr[9] = s(meta.get("order_number"))
    hdr[10] = ""
    hdr[11] = f"\"{s(meta.get('supplier_short_name'))}\""
    hdr[12] = f"\"{s(meta.get('supplier_short_name'))}\""
    hdr[13] = f"\"{s(meta.get('supplier_name'))}\""
    hdr[14] = f"\"{s(meta.get('supplier_city'))}\""
    hdr[15] = f"\"{s(meta.get('supplier_postal_zip_code'))}\""
    hdr[16] = f"\"{s(meta.get('supplier_address(street_and_number)'))}\""
    hdr[17] = f"\"{s(meta.get('supplier_nip'))}\""
    hdr[18] = ""
    hdr[19] = ""
    hdr[20] = f"\"{s(meta.get('city_where_invoice_was_issued'))}\""
    hdr[21] = s(meta.get("invoice_date"))
    hdr[22] = s(meta.get("sales_date"))
    hdr[23] = s(meta.get("invoice_date"))
    hdr[24] = s(meta.get("number_of_lines"))
    hdr[25] = "1"
    hdr[26] = ""
    hdr[27] = s(meta.get("net_value_of_the_whole_invoice", "0"))
    hdr[28] = s(meta.get("VAT/TVA_value_of_the_whole_invoice", "0"))
    hdr[29] = s(meta.get("gross_value_of_the_whole_invoice", "0"))
    hdr[30] = s(meta.get("gross_value_of_the_whole_invoice", "0"))
    hdr[31] = s(meta.get("rebate_name(if_granted)", "0"))
    hdr[32] = s(meta.get("rebate_value(if_granted)", "0"))
    hdr[33] = f"\"{s(meta.get('payment_method'))}\""
    hdr[34] = s(meta.get("date_of_payment"))
    hdr[35] = s(meta.get("amount_already_paid", "0"))
    hdr[36] = s(meta.get("gross_value_of_the_whole_invoice", "0"))
    hdr[37] = "0"
    hdr[38] = "0"
    hdr[39] = "1"
    hdr[40] = "0"
    hdr[41] = '"Osoba wystawiająca"'
    hdr[42] = '"Osoba odbierająca"'
    hdr[43] = '""'
    hdr[44] = "0.0000"
    hdr[45] = "0.0000"
    hdr[46] = f"\"{s(meta.get('currency_of_the_invoice'))}\""
    hdr[47] = "1.0000"
    hdr[48] = '""'
    hdr[49] = '""'
    hdr[50] = '""'
    hdr[51] = ""
    hdr[52] = "0"
    hdr[53] = "0"
    hdr[54] = "0"
    hdr[55] = '""'
    hdr[56] = '0.0000'
    hdr[57] = '""'
    hdr[58] = '0.0000'
    hdr[59] = s(meta.get("suppliers_country", "0"))
    hdr[60] = s(meta.get("suppliers_country_prefix", "0"))
    hdr[61] = "1"

    r[0] = '"23"'
    r[1] = s(meta.get("VAT/TVA_rate", "0"))
    r[2] = s(meta.get("net_value_of_the_whole_invoice", "0"))
    r[3] = s(meta.get("VAT/TVA_value_of_the_whole_invoice", "0"))
    r[4] = s(meta.get("gross_value_of_the_whole_invoice", "0"))
    r[5] = s(meta.get("net_value_of_the_whole_invoice", "0"))
    r[6] = s(meta.get("VAT/TVA_value_of_the_whole_invoice", "0"))
    r[7] = s(meta.get("gross_value_of_the_whole_invoice", "0"))
    r[8] = '0.0000'
    r[9] = '0.0000'
    r[10] = '0.0000'
    r[11] = '0.0000'
    r[12] = '0.0000'
    r[13] = '0.0000'
    r[14] = '0.0000'
    r[15] = '0.0000'
    r[16] = '0.0000'
    r[17] = '0.0000'


    join = lambda r: ",".join(map(str, r))
    lines = [
        "[INFO]",
        join(info),
        "[NAGLOWEK]",
        join(hdr),
        "[ZAWARTOSC]",
        join(r),
        "",
    ]
    with open(epp_path, "wb") as f:
        f.write("\r\n".join(lines).encode("cp1250"))


if __name__ == "__main__":
    gdrive_batch_convert_json_to_epp(
        gdrive_src=OUTPUT_DIR,
        dst_subfolder="epps",
        mount_if_needed=True,
    )
