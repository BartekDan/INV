import os
import base64
from pathlib import Path
from tqdm import tqdm
import openai

# Fields to extract from the invoice OCR
FIELDS_TO_EXTRACT = [
    "invoice_number",
    "inoice_number_of_document_being_correcterd (if_this_document_corrects_different_invoice)",
    "data_of_document_being_corretcted (if_this_document_corrects_different_invoice)",
    "order_number",
    "invoice_date",
    "invoice_due_date",
    "issue_date",
    "buyer_name",
    "buyer_short_name",
    "buyer_city",
    "buyer_postal_zip_code",
    "byuer_address(street_and_number)",
    "byuer_nip",
    "byuer_country",
    "supplier_nip",
    "supplier_name",
    "supplier_short_name",
    "supplier_city",
    "supplier_postal_zip_code",
    "supplier_address(street_and_number)",
    "supplier_country",
    "suppliers_country_prefix",
    "city_where_invoice_was_issued",
    "sales_date",
    "date_of_receiving",
    "number_of_lines",
    "net_value_of_the_whole_invoice",
    "VAT/TVA_value_of_the_whole_invoice",
    "gross_value_of_the_whole_invoice",
    "currency_of_the_invoice",
    "payment_method",
    "date_of_payment",
    "amount_already_paid",
    "outstanding_amount",
    "rebate_name(if_granted)",
    "rebate_value(if_granted)",
    "name_of_the_person_issuing_the_invoice",
    "name_of_the_person_receiving_the_invoice",
]

IMG_EXTS = (".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".gif", ".webp")


def ocr_image(image_path: str) -> str:
    """Run OCR on *image_path* using an OpenAI vision model."""
    with open(image_path, "rb") as fh:
        img_b64 = base64.b64encode(fh.read()).decode()

    blocks = [
        {
            "type": "text",
            "text": (
                "Extract ALL text from this invoice image. Return only raw text in Polish. "
                "For any date reutrn it in YYYY-MM_DD format, don't give time. "
                "For currency return PLN, USD, EUR not zł, $, E. "
                "If any data are in foreign langugage translate it to Polish"
            ),
        },
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"},
        },
    ]

    rsp = openai.chat.completions.create(
        model="o4-mini",
        reasoning_effort="high",
        messages=[{"role": "user", "content": blocks}],
    )
    return rsp.choices[0].message.content


def save_invoice_json(img_path: str, out_path: str) -> None:
    """Save extracted fields from *img_path* to *out_path* as JSON."""
    raw_text = ocr_image(img_path)

    prompt = (
        "Using ONLY the OCR text below, extract EXACTLY these keys:\n"
        + ", ".join(FIELDS_TO_EXTRACT)
        + "\nReturn a compact JSON object with exactly those keys.\n\nOCR:\n"
        + raw_text
    )

    rsp = openai.chat.completions.create(
        model="o4-mini",
        reasoning_effort="high",
        messages=[
            {
                "role": "system",
                "content": "You output strict JSON; no extra keys, no comments.",
            },
            {"role": "user", "content": prompt},
        ],
    )

    json_str = rsp.choices[0].message.content.strip()
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(json_str)

    print(f"\u2705 {Path(out_path).name}")
    print(json_str)


def batch_ocr_images(source_dir: str, output_dir: str | None = None) -> None:
    """Run OCR for every invoice image in *source_dir*."""
    src = Path(source_dir)
    if output_dir is None:
        out = src / "json"
    else:
        out = Path(output_dir)
    out.mkdir(exist_ok=True)

    img_files = sorted(p for p in src.rglob("*") if p.suffix.lower() in IMG_EXTS)
    print(f"\U0001F50E Found {len(img_files)} images in {src}")

    for img_path in tqdm(img_files, desc="Processing scans"):
        out_json = out / f"{img_path.stem}.json"
        try:
            save_invoice_json(str(img_path), str(out_json))
        except Exception as e:
            print(f"\u274C Failed on {img_path.name}: {e}")

    print("\n\U0001F389 All done! JSON files are in:", out)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="OCR invoice images to JSON")
    parser.add_argument("source_dir", help="Folder containing invoice scans")
    parser.add_argument(
        "--output-dir", default=None, help="Where to place JSON files (default: <source_dir>/json)"
    )

    args = parser.parse_args()
    batch_ocr_images(args.source_dir, args.output_dir)
