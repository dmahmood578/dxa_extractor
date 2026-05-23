# DXA Data Extractor

This repository contains scripts to automatically extract demographics and bone mineral density (BMD), T-score, and Z-score measurements from raw Dual-energy X-ray Absorptiometry (DXA) DICOM files.

**IMPORTANT: This tool processes Protected Health Information (PHI). Data remains local and is not uploaded anywhere.**

## Prerequisites

1. **Python 3.x**
2. **Tesseract OCR**: Required to read the text off the DXA report images.
   - The scripts use the `tesseract` command from your system PATH. Make sure it is installed and available in your terminal.
3. **Python Environment Setup**: 
   It's highly recommended to use a virtual environment to manage dependencies:
   ```bash
   # Create a virtual environment
   python -m venv venv
   
   # Activate it (Mac/Linux)
   source venv/bin/activate
   # Or on Windows:
   # venv\Scripts\activate

   # Install the required libraries
   pip install -r requirements.txt
   ```

## Core Workflow

To process a new batch of DXA scans, follow these steps:

### 1. Data Placement
Ensure your raw DICOM folders are placed in a directory named `CLD DXA` adjacent to or containing the patient folders. The folder structure is expected to look like:
```text
CLD DXA/
  ├── 1/
  │   └── DICOM/ ...
  ├── 2/
  ...
dxa_extractor/
  ├── extract_all_data.py
  ├── dxa_to_excel.py
  ...
```

### 2. Extract Images & Run OCR
```bash
cd dxa_extractor
python extract_all_data.py
```
**What it does:**
- Scans all patient DICOM folders in `CLD DXA/`.
- Extracts the embedded DXA report pages as PNG images into `extracted_images/`.
- Runs Tesseract OCR on the images and saves the raw text output to `extracted_text/`.

### 3. Parse Data to Excel (Main Extraction)
```bash
python dxa_to_excel.py
```
**What it does:**
- Parses the OCR'd text files to extract:
  - Patient Demographics (Name, DOB, Age, Height, Weight, Sex, Scan Date, Referring MD)
  - AP Spine L1-L4 (BMD, T-score, Z-score)
  - Left & Right Femur - Neck and Total (BMD, T-score, Z-score)
  - TBS (Trabecular Bone Score)
- Accounts for common OCR artifacts and GE Lunar / Hologic layout variations.
- Outputs the finalized data table to `dxa_data.xlsx` with T-score-based color coding (e.g. yellow for osteopenia, red for osteoporosis).

### 4. Extract DICOM Demographics (Optional)
```bash
python list_all_patients.py
```
**What it does:**
- Bypasses OCR and reads patient metadata directly from the DICOM headers.
- Saves `patient_cohort_demographics.csv` into the `data/` folder.

## Troubleshooting & Debugging Scripts

This directory includes several auxiliary scripts for debugging extraction issues:

- **`test_final_parser.py` / `draft_parser.py`**: Sandbox scripts for testing regex patterns against OCR text.
- **`extract_numeric_lines.py`**: Prints all lines from the OCR output that resemble data tables to help locate missing numbers.
- **`inspect_dxa_file.py` / `dicom_inspect.py` / `sr_dump.py`**: Dumps raw DICOM headers and Structured Report (SR) tags to the console to see what raw text/data is natively available before OCR.
- **`test_hologic_ocr.py`**: Tests different Tesseract Page Segmentation Modes (PSM) for difficult Hologic scans.

## Note on OCR Artifacts
The parser in `dxa_to_excel.py` has a built-in mapping (`_OCR_SIGN_MAP`) to handle common Tesseract misreads (e.g., converting `O4` to `-0.4`, or `24` to `-2.4`). If new scans consistently fail to parse certain numbers, check the raw text in `extracted_text/` and update the map or regex inside `dxa_to_excel.py` as needed.
