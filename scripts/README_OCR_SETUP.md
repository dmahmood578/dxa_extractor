# OCR Setup and Multi-Backend Guide (Tesseract, Paddle, Surya)

This document covers the full OCR pipeline for DXA extraction: the default Tesseract path, alternative PaddleOCR and Surya backends, comparison workflows, and instructions for tuning heuristics to your dataset.

---

## 1. System Dependencies (Install First)

### Tesseract OCR

Tesseract is not a Python package — it must be installed at the OS level before running the default pipeline.

| OS | Command |
|----|---------|
| macOS (Homebrew) | `brew install tesseract` |
| Windows | Download from [UB-Mannheim/tesseract](https://github.com/UB-Mannheim/tesseract/wiki). During install, check "Add Tesseract to system PATH" or add `C:\Program Files\Tesseract-OCR\` manually. |
| Linux (apt) | `sudo apt install tesseract-ocr` |

Verify:
```bash
tesseract --version
```

### llama.cpp (Surya only)

Required only if you intend to run the Surya LLM backend.

| OS | Command |
|----|---------|
| macOS (Homebrew) | `brew install llama.cpp` |
| Windows / Linux | Download from [llama.cpp releases](https://github.com/ggerganov/llama.cpp/releases). Place `llama-server` on your PATH. |

## 2. Installing Python Packages

Install in the same `.venv` (Python 3.11):

```bash
source .venv/bin/activate

# Core runtime (Tesseract path only):
pip install -r requirements.txt

# PaddleOCR (CPU-only, lightweight):
pip install paddlepaddle paddleocr

# Surya (LLM-backed, heavier — requires llama.cpp from Section 1):
pip install surya-ocr opencv-python
```

After install, Paddle model files cache at `~/.paddlex/official_models/`. Surya downloads models on first run (several GB).

---

## 3. Recommended Default Setup (Tesseract)

Once system dependencies and Python packages are installed, the simplest and fastest path is:

```bash
source .venv/bin/activate
python extract_all_data.py       # extract images + run Tesseract OCR
python dxa_to_wide_csv.py        # parse into data/patient_wide_measurements.csv
python dxa_to_excel.py           # (optional) parse into dxa_data.xlsx
```

Tesseract is the default because it is stable, fast, and already tuned for common DXA OCR artifacts. Outputs go to `extracted_text/Patient_<n>/`.

---

## 4. Running Alternative Backends

### 4a. PaddleOCR — Batch Mode (Fast, Single-Process)

Reuses one model instance across all images — fastest for CPU. The parser in `dxa_to_wide_csv.py` now automatically handles Paddle's clean text format via a loose-section fallback, extracting demographics, all BMD/T/Z regions, per-vertebra values, and TBS.

```bash
# Run OCR
python scripts/run_paddle_batch.py \
  --input extracted_images \
  --outdir ocr_compare \
  --ext png \
  --skip-existing

# Reorganize for parser
python scripts/paddle_to_parser_layout.py \
  --paddle-dir ocr_compare --outdir paddle_text

# Full parse (same parser as Tesseract, with auto-adaptive mode)
python dxa_to_wide_csv.py \
  --text-source paddle_text \
  --output data/paddle_wide_measurements.csv
```

### 4b. PaddleOCR — Parallel Mode (Multi-Core)

Uses N worker processes, each with its own model. Recommended for 4+ CPU cores and 50+ images:

```bash
python scripts/run_paddle_parallel.py \
  --input extracted_images \
  --outdir ocr_compare \
  --workers 4 \
  --skip-existing
```

Set `--workers` to `cpu_count` or fewer. Each worker initializes its own PaddleOCR model once and processes a partition of images.

### 4c. Surya (LLM) — Per-Patient via Harness

Surya is heavy (~2–4 minutes per image). Run only on patients where other backends failed:

```bash
python scripts/run_ocr_harness.py \
  --input extracted_images/Patient_3 \
  --output ocr_compare/patient_3 \
  --python ./.venv/bin/python \
  --exts png
```

Output: `ocr_compare/patient_<n>/surya/<image>.png/<image>/results.json`

---

## 5. Merging OCR Outputs into the Master CSV

After running a backend, merge its detected BMD/T-score values into `data/patient_wide_measurements.csv`:

### Surya to CSV
```bash
python scripts/merge_surya_to_csv.py \
  --surya-dir ocr_compare/patient_3/surya \
  --csv data/patient_wide_measurements.csv \
  --folder 3
```

### Paddle to CSV
```bash
python scripts/merge_paddle_to_csv.py \
  --paddle-dir ocr_compare/patient_3/paddle \
  --csv data/patient_wide_measurements.csv \
  --folder 3
```

Both scripts:
- Match the patient row by `--folder` (1-indexed patient number) or `--name`.
- Apply sanity checks (BMD 0.1–3.0 g/cm², |T-score| ≤ 15).
- Create a `.bak` or `.bak_paddle` backup before writing.

---

## 6. Comparing Backends and Generating Reports

For a single patient, generate a comparison CSV and markdown summary:

```bash
# Generate comparison CSV:
python scripts/compare_ocr_backends.py \
  --folder 3 \
  --out ocr_compare/patient_3/compare_summary.csv

# Convert to readable markdown:
python scripts/compare_csv_to_md.py \
  --csv ocr_compare/patient_3/compare_summary.csv \
  --out ocr_compare/patient_3/compare_summary.md
```

The comparison script collects evidence from:
- `data/patient_wide_measurements.csv` (master parsed values)
- `ocr_compare/patient_<n>/surya/` (Surya JSON --- table HTML parsing)
- `ocr_compare/patient_<n>/paddle/` (Paddle JSON --- heuristic line extraction)
- `extracted_text/Patient_<n>/` (Tesseract raw text)

---

## 7. Full Analysis Pipeline (All Steps)

> **Shortcut:** `python scripts/run_full_pipeline.py --step all --skip-surya` runs steps 1–7 below automatically. See `--help` for flags.

To run the complete multi-backend extraction on all patients manually:

```bash
source .venv/bin/activate

# Step 1: Tesseract extraction (default, fast)
python extract_all_data.py

# Step 2: Parse Tesseract output → CSV
python dxa_to_wide_csv.py

# Step 3: Run Paddle OCR batch (model reuse, skip existing)
python scripts/run_paddle_batch.py \
  --input extracted_images --outdir ocr_compare \
  --ext png --skip-existing

# Step 4: Reorganize Paddle text into parser-compatible layout
python scripts/paddle_to_parser_layout.py \
  --paddle-dir ocr_compare --outdir paddle_text

# Step 5: Full parse of Paddle text (demographics + all BMD/T/Z regions)
python dxa_to_wide_csv.py \
  --text-source paddle_text \
  --output data/paddle_wide_measurements.csv

# Step 6 (optional, heavy): Run Surya on patients with poor Tesseract/Paddle agreement
# python scripts/run_ocr_harness.py --input extracted_images/Patient_<n> ...

# Step 7: Generate comparison reports for each patient
for folder in $(seq 1 20); do
  python scripts/compare_ocr_backends.py \
    --folder "${folder}" \
    --out "ocr_compare/patient_${folder}/compare_summary.csv" 2>/dev/null || true
  python scripts/compare_csv_to_md.py \
    --csv "ocr_compare/patient_${folder}/compare_summary.csv" \
    --out "ocr_compare/patient_${folder}/compare_summary.md" 2>/dev/null || true
done
```

---

## 8. Refining Heuristics and Parameters

### Tesseract

Edit `dxa_to_excel.py` (or `dxa_to_wide_csv.py`). The parser now works with any OCR backend — it automatically falls back to loose-section parsing when clean (Paddle/Surya) text doesn't have multi-column rows.

- **`_OCR_SIGN_MAP`** — maps common misreads (e.g., `O4` → `-0.4`, `24` → `-2.4`). Add entries for systematic errors you observe.
- **PSM modes** — test different Page Segmentation Modes in `test_hologic_ocr.py`:
  - PSM 6: uniform block of text (default for DXA tables)
  - PSM 3: fully automatic (good for mixed layouts)
  - PSM 4: single column of text
- **Whitelist** — in `extract_all_data.py`, the numeric pass uses `-c tessedit_char_whitelist=...`. Adjust to include/exclude characters.
- **Loose mode** — `find_ancillary_section_loose()` uses `_REGION_LABELS_RE` to group lines by region labels. Add manufacturer-specific region terms here if table rows aren't being detected.

### PaddleOCR

Edit `scripts/paddle_line_extract.py` (single-image) or `scripts/run_paddle_batch.py` (batch). Key heuristics:

| Parameter | Location | Effect |
|-----------|----------|--------|
| `num_re` regex | `re.compile(r'(-?\d+\.\d+)')` | Controls which numbers are considered BMD candidates |
| Context window | `lines[max(0, i-2):i+3]` | Lines before/after a keyword match. Narrow to reduce false positives. |
| Sanity range | `0.1 <= fval <= 3.0` | BMD valid range (g/cm²). Adjust for your population. |
| T-score bound | `abs(float(tv)) <= 15` | Reject implausible T-scores. |
| Region keywords | `['neck', 'total', 'spine', 'l1', ...]` | Add manufacturer-specific terms (e.g., `"femur"`, `"ward"`, `"troch"`). |

**To reduce false positives:**
1. Narrow the context window to `lines[i:i+2]`.
2. Require a column header line (`region`, `bmd`, `t-score`) within 3 lines above the candidate.
3. Reject candidates where nearby text contains `area`, `bmc`, `width`, `height` (non-BMD columns).

### Surya

Edit `scripts/merge_surya_to_csv.py`. Key areas:

- **Header detection** (line ~50): looks for `region`, `area`, `bmd` in first 3 rows of `<table>`. Adjust keywords for your DXA report format.
- **Column mapping** (line ~60): `idx_bmd` and `idx_t` are determined by `'bmd' in hl` / `'t-score' in hl`. Add patterns for `"bmd (g/cm^2)"`, `"t-score (sd)"`, etc.
- **Sanity checks** (line ~75): BMD range and T-score bound — same as Paddle.

---

## 9. Performance Tuning

| Backend | Speed | Accuracy | Best for |
|---------|-------|----------|----------|
| Tesseract | ~1s/image | Good (tuned) | Default first pass |
| Paddle (batch) | ~2–10s/image | Better than Tesseract on noisy fonts | Fallback / validation |
| Paddle (parallel) | ~(2–10s)/N per image | Same as batch | Large batches (50+ images) |
| Surya | ~2–5 min/image | Best for tables with headers | Failure recovery only |

**Tips:**
- Always use `--skip-existing` to resume interrupted runs.
- Paddle model files (`~/.paddlex/`) are re-downloaded only on first run.
- Surya model files are large (~5–10 GB). Run Surya only on patients where Tesseract and Paddle disagree significantly.
- Monitor: `ps aux | egrep 'paddle|llama|surya'` to see active jobs.
- Kill Surya: `pkill -f llama-server` (use with care).

---

## 10. Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `SpawnError` / missing `llama-server` | llama.cpp not installed | `brew install llama.cpp` |
| `Could not initialize PPStructure` | Paddle PPStructure API mismatch | Use `paddle_line_extract.py` or batch runner instead |
| Paddle warnings about `use_angle_cls` | API deprecation | Harmless; switch to `use_textline_orientation` if desired |
| `libpng error: IDAT: CRC error` | Corrupt extracted PNG | Re-run `extract_all_data.py` for that patient |
| Merge script finds no matching row | Folder/name mismatch | Use `--folder <n>` instead of `--name` |
| BMD values all empty after merge | Sanity checks too strict | Widen BMD range or check source JSON/TXT for actual numbers |
