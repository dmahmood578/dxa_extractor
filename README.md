# DXA Data Extractor

This repository contains scripts to automatically extract demographics and bone mineral density (BMD), T-score, and Z-score measurements from raw Dual-energy X-ray Absorptiometry (DXA) DICOM files.

**IMPORTANT: This tool processes Protected Health Information (PHI). Data remains local and is not uploaded anywhere.**

## Prerequisites

### System dependencies (install once per machine)

**Tesseract OCR** — not a Python package; must be installed at the OS level.

| OS | Command |
|----|---------|
| macOS (Homebrew) | `brew install tesseract` |
| Windows | Download installer from [UB-Mannheim/tesseract](https://github.com/UB-Mannheim/tesseract/wiki). Ensure `tesseract.exe` is on your PATH (typically `C:\Program Files\Tesseract-OCR\`). |
| Linux (apt) | `sudo apt install tesseract-ocr` |

Verify installation:
```bash
tesseract --version
```

**llama.cpp** (only needed for the optional Surya LLM backend):

| OS | Command |
|----|---------|
| macOS (Homebrew) | `brew install llama.cpp` |
| Windows / Linux | See [llama.cpp releases](https://github.com/ggerganov/llama.cpp/releases) — download a prebuilt binary or build from source. |

### Python environment (created once per project)

- **Python 3.9+** (recommended: 3.11)

  ```bash
  python3.11 -m venv .venv
  source .venv/bin/activate      # macOS / Linux
  # .venv\Scripts\activate       # Windows
  pip install -r requirements.txt
  ```

## Core Workflow

### Quick Start (Tesseract only)

```bash
cd dxa_extractor
source .venv/bin/activate
python extract_all_data.py          # extract images + OCR
python dxa_to_wide_csv.py           # parse → data/patient_wide_measurements.csv
```

### Unified Master Runner

The master runner (`scripts/run_full_pipeline.py`) handles all backends and stages:

```bash
# Everything except Surya (fastest recommended path):
python scripts/run_full_pipeline.py --step all --skip-surya

# Paddle with 4 CPU workers (omit --workers for single-process, default):
python scripts/run_full_pipeline.py --step paddle --workers 4

# Individual stages:
python scripts/run_full_pipeline.py --step tesseract     # default OCR + wide CSV
python scripts/run_full_pipeline.py --step paddle        # Paddle OCR + full parse (single-process)
python scripts/run_full_pipeline.py --step compare       # per-patient backend comparisons
python scripts/run_full_pipeline.py --step validate      # agreement report → flags gaps
python scripts/run_full_pipeline.py --step surya --patient 3   # Surya fallback (slow)

# Stage scoped to one patient:
python scripts/run_full_pipeline.py --step compare --patient 3

# Preview commands without running:
python scripts/run_full_pipeline.py --step all --dry-run
```

**Output files produced:**

| File | Source | Contents |
|------|--------|----------|
| `data/patient_wide_measurements.csv` | Tesseract | Demographics + all BMD/T/Z regions + per-vertebra + TBS |
| `data/paddle_wide_measurements.csv` | Paddle | Same schema, independent extraction |
| `data/validation_report.md` | Validate step | Patient-by-patient Tesseract vs Paddle agreement; Surya recommendations |
| `ocr_compare/patient_N/compare_summary.md` | Compare step | Per-patient 3-way comparison (Tesseract/Paddle/Surya) |

### Step-by-step (manual control)

<details><summary>Click to expand — individual scripts</summary>

#### 1. Data Placement
Raw DICOM folders go in `CLD DXA/` adjacent to the repo root:

```text
CLD DXA/
  ├── 1/  (DICOM/)
  ├── 2/
  ...
dxa_extractor/
  ├── extract_all_data.py
  ...
```

#### 2. Extract images + Tesseract OCR
```bash
python extract_all_data.py
```
→ `extracted_images/Patient_N/` and `extracted_text/Patient_N/`

#### 3. Parse to wide CSV
```bash
python dxa_to_wide_csv.py
```
→ `data/patient_wide_measurements.csv` (demographics + all BMD/T/Z regions)

#### 4. DICOM demographics (optional)
```bash
python list_all_patients.py
```
→ `data/patient_cohort_demographics.csv`

#### 5. Excel output (optional)
```bash
python dxa_to_excel.py
```
→ `dxa_data.xlsx` with T-score color coding.

</details>

## 5. Multi-Backend OCR (Paddle, Surya)

The project supports PaddleOCR and Surya as alternative OCR backends. The unified master runner handles all stages — see **Core Workflow** above. Full details in **[scripts/README_OCR_SETUP.md](scripts/README_OCR_SETUP.md)**.

### Quick install (optional backends)

```bash
# Activate the venv FIRST — otherwise pip installs system-wide:
source .venv/bin/activate          # macOS / Linux
# .venv\Scripts\activate           # Windows

pip install paddlepaddle==2.6.2 paddleocr==2.7.3   # PaddleOCR (pin both — 3.x PaddleOCR requires Paddle 3.x which has Windows bugs)
pip install surya-ocr opencv-python         # Surya (macOS/Linux only)
brew install llama.cpp                      # Surya dependency (macOS)
```

### Master runner commands

```bash
python scripts/run_full_pipeline.py --step paddle              # Paddle OCR + full parse
python scripts/run_full_pipeline.py --step validate            # Agreement report
python scripts/run_full_pipeline.py --step surya --patient 3   # Surya fallback on patient 3
python scripts/run_full_pipeline.py --step all --skip-surya    # Everything except Surya
```

### Troubleshooting

| Symptom | Fix |
|---------|-----|
| `SpawnError` / missing `llama-server` | `brew install llama.cpp` |
| Paddle `PPStructure` init error | Use `run_paddle_batch.py` or `run_paddle_parallel.py` instead |
| Paddle `ConvertPirAttribute…` / `onednn_instruction.cc` (Windows) | PaddlePaddle 3.x oneDNN bug on Windows. Use `paddlepaddle==2.6.2 paddleocr==2.7.3` |
| Paddle `set_optimization_level` error | PaddleOCR 3.x + PaddlePaddle 2.x mismatch. Use `paddlepaddle==2.6.2 paddleocr==2.7.3` |
| `libpng error: IDAT: CRC error` | Re-run `extract_all_data.py` for that patient |
| Merge finds no matching row | Use `--folder <n>` instead of `--name` |
| Runs are slow | Check `ps aux \| egrep 'paddle\|llama\|surya'`; verify model cache at `~/.paddlex/` |
| Abort Surya/llama | `pkill -f llama-server` |
| Pipeline step fails silently | Run with `--dry-run` to preview commands, then execute individually |

### Backend comparison

| Backend | Speed per image | Best for |
|---------|----------------|----------|
| Tesseract | ~1 s | Default first pass |
| Paddle (batch) | ~2–10 s | Validation, noisy fonts |
| Paddle (parallel) | ~(2–10)/N s | Large batches (50+ images, 4+ cores) |
| Surya (LLM) | ~2–5 min | Failure recovery only |

### Heuristics tuning (quick reference)

| Backend | Files to edit | Key parameters |
|---------|--------------|----------------|
| Tesseract | `dxa_to_wide_csv.py` | `_OCR_SIGN_MAP`, PSM mode, `_REGION_LABELS_RE` (loose mode) |
| Paddle | `scripts/paddle_line_extract.py` | `num_re` regex, context window, BMD sanity range (0.1–3.0) |
| Surya | `scripts/merge_surya_to_csv.py` | Header detection keywords, column index mapping |

## 6. Troubleshooting & Debugging Scripts

This directory includes several auxiliary scripts for debugging extraction issues:

- **`test_final_parser.py` / `draft_parser.py`**: Sandbox scripts for testing regex patterns against OCR text.
- **`extract_numeric_lines.py`**: Prints all lines from the OCR output that resemble data tables to help locate missing numbers.
- **`inspect_dxa_file.py` / `dicom_inspect.py` / `sr_dump.py`**: Dumps raw DICOM headers and Structured Report (SR) tags to the console to see what raw text/data is natively available before OCR.
- **`test_hologic_ocr.py`**: Tests different Tesseract Page Segmentation Modes (PSM) for difficult Hologic scans.

## 7. OCR Artifacts & Parser Notes

The parsers in `dxa_to_wide_csv.py` and `dxa_to_excel.py` share a built-in mapping (`_OCR_SIGN_MAP`) to handle common Tesseract misreads (e.g., converting `O4` to `-0.4`, or `24` to `-2.4`). If new scans consistently fail to parse certain numbers, check the raw text in `extracted_text/` and update the map or regex inside `dxa_to_wide_csv.py` as needed.

The wide-CSV parser (`dxa_to_wide_csv.py`) now supports any OCR backend (Tesseract, Paddle, Surya) via an automatic loose-section fallback (`find_ancillary_section_loose`). When the tight, multi-column Tesseract-style row detection finds too few rows, the parser re-groups clean OCR text by region labels (L1–L4, Neck, Total, etc.) and re-attempts extraction. Use `--text-source <dir>` to point the parser at any OCR output directory.
