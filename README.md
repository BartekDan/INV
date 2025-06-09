# JSON to EDI++ Conversion Agent

This repository contains a simple Python agent that watches the `invoices_json/` directory
for JSON invoice files. When a file appears it is converted into the EDI++ 1.11 `.epp`
format using `json_to_epp.py`.

The agent validates the output and, if validation fails, asks an OpenAI model for a patch
to fix the converter. Patched versions of the converter are stored in `script_versions/`.

Final valid files are placed in `epp_repaired/`.

The repository also contains `json_to_epp.py` which can be run on its own to
convert a folder of JSON invoice files into `.epp` files.  See the
`gdrive_batch_convert_json_to_epp` and `batch_convert_json_to_epp` functions
inside that script for Google Drive and local batch modes respectively.

## Installation

```bash
pip install -r requirements.txt
```

## Running

```bash
python agent.py
```

Place JSON invoice files in `invoices_json/` and monitor the logs in `logs/agent.log`.
