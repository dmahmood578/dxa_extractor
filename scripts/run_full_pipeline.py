#!/usr/bin/env python3
"""
DXA Extraction Pipeline — Master Runner
========================================
End-to-end orchestrator for Tesseract, Paddle, and Surya OCR backends.

Usage:
  python scripts/run_full_pipeline.py --step tesseract                         # default OCR + wide CSV
  python scripts/run_full_pipeline.py --step paddle --workers 4                 # Paddle OCR + full parse
  python scripts/run_full_pipeline.py --step surya --patient 3                  # Surya on one patient
  python scripts/run_full_pipeline.py --step compare                            # compare all backends
  python scripts/run_full_pipeline.py --step validate                           # patient-by-patient validation report
  python scripts/run_full_pipeline.py --step all --workers 4 --skip-surya       # everything except Surya

Flags:
  --step {tesseract,paddle,surya,compare,validate,all}   which pipeline stage(s) to run
  --patient N                                             limit to patient folder N
  --workers N                                             CPU workers for parallel Paddle
  --skip-tesseract / --skip-paddle / --skip-surya         skip individual backends in --step all
  --dry-run                                               print commands without executing
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _SCRIPT_DIR.parent

def _resolve_project_python() -> str:
    """Prefer the repository .venv Python so subprocesses use the project env.

    This avoids accidentally inheriting an Anaconda/system interpreter when the
    shell activation did not switch the current terminal the way the user expected.
    """
    if os.name == "nt":
        candidate = _PROJECT_DIR / ".venv" / "Scripts" / "python.exe"
    else:
        candidate = _PROJECT_DIR / ".venv" / "bin" / "python"

    if candidate.exists():
        return str(candidate)

    # Fall back to the interpreter that launched this script.
    return sys.executable


_VENV_PYTHON = _resolve_project_python()

# ── helpers ───────────────────────────────────────────────────────────────────

def run(cmd: list[str], dry: bool = False, cwd: str | None = None) -> int:
    """Run a command; return exit code."""
    cmd_str = " ".join(cmd)
    print(f"\n  \033[36m{cmd_str}\033[0m", flush=True)
    if dry:
        return 0
    # Ensure Paddle oneDNN / PIR flags are in the child process's actual OS
    # environment from birth — Paddle's C++ layer reads them before Python's
    # os.environ modifications take effect inside the script.
    env = os.environ.copy()
    env.setdefault("FLAGS_use_mkldnn", "0")
    env.setdefault("FLAGS_enable_pir_api", "0")
    env.setdefault("KMP_AFFINITY", "disabled")
    result = subprocess.run(cmd, cwd=cwd or str(_PROJECT_DIR), env=env)
    return result.returncode


def available_patients(text_dir: Path) -> list[str]:
    """Return sorted list of patient folder numbers found under text_dir."""
    if not text_dir.is_dir():
        return []
    nums = []
    for d in text_dir.iterdir():
        if d.is_dir() and d.name.lower().startswith("patient_"):
            n = "".join(c for c in d.name if c.isdigit())
            if n:
                nums.append(n)
    return sorted(nums, key=lambda v: int(v) if v.isdigit() else 999)


def _copy_metadata_for_paddle(args: argparse.Namespace) -> None:
    """Copy GE/Hologic metadata files from Tesseract output to Paddle text dir.

    This ensures the parser can apply table-only filtering for GE scans even
    when using the Paddle backend (which has its own text directory).  The
    metadata is originally created by the Tesseract step.
    """
    tesseract_dir = _PROJECT_DIR / "extracted_text"
    paddle_dir = _PROJECT_DIR / "paddle_text"
    if not tesseract_dir.is_dir() or not paddle_dir.is_dir():
        return
    copied = 0
    for patient_dir in tesseract_dir.iterdir():
        if not patient_dir.is_dir() or not patient_dir.name.startswith("Patient_"):
            continue
        dest_dir = paddle_dir / patient_dir.name
        if not dest_dir.is_dir():
            continue
        for meta_file in ("_manufacturer.txt", "_table_only.txt"):
            src = patient_dir / meta_file
            if src.exists():
                import shutil
                shutil.copy2(src, dest_dir / meta_file)
                copied += 1
    if copied and not args.dry_run:
        print(f"  Copied {copied} GE/Hologic metadata files to paddle_text/")


# ── stages ────────────────────────────────────────────────────────────────────

def step_tesseract(args: argparse.Namespace) -> int:
    """Run Tesseract extraction + wide CSV parse."""
    print("\n\033[1m=== TESSERACT EXTRACTION ===\033[0m")
    rc = run([_VENV_PYTHON, "extract_all_data.py"], dry=args.dry_run)
    if rc != 0:
        print("  Tesseract extraction failed — stopping.")
        return rc

    print("\n\033[1m=== TESSERACT → WIDE CSV ===\033[0m")
    rc = run([_VENV_PYTHON, "dxa_to_wide_csv.py"], dry=args.dry_run)
    return rc


def step_paddle(args: argparse.Namespace) -> int:
    """Run Paddle OCR (batch or parallel), reorganize, and full parse."""
    workers = getattr(args, 'workers', 1) or 1

    if workers > 1:
        print(f"\n\033[1m=== PADDLE OCR (PARALLEL — {workers} workers) ===\033[0m")
        paddle_cmd = [
            _VENV_PYTHON, "scripts/run_paddle_parallel.py",
            "--input", "extracted_images",
            "--outdir", "ocr_compare",
            "--workers", str(workers),
            "--ext", "png",
            "--skip-existing",
        ]
    else:
        print("\n\033[1m=== PADDLE OCR (BATCH — single-process) ===\033[0m")
        paddle_cmd = [
            _VENV_PYTHON, "scripts/run_paddle_batch.py",
            "--input", "extracted_images",
            "--outdir", "ocr_compare",
            "--ext", "png",
            "--skip-existing",
        ]
    rc = run(paddle_cmd, dry=args.dry_run)
    if rc != 0:
        print("  Paddle OCR failed — stopping.")
        return rc

    print("\n\033[1m=== REORGANIZE PADDLE TEXT ===\033[0m")
    rc = run([
        _VENV_PYTHON, "scripts/paddle_to_parser_layout.py",
        "--paddle-dir", "ocr_compare",
        "--outdir", "paddle_text",
    ], dry=args.dry_run)
    if rc != 0:
        print("  Paddle reorganize failed — stopping.")
        return rc

    # Copy GE/Hologic metadata from Tesseract output to Paddle text dir
    # so the parser can apply table-only filtering for GE scans.
    _copy_metadata_for_paddle(args)

    print("\n\033[1m=== PADDLE → WIDE CSV (FULL PARSE) ===\033[0m")
    rc = run([
        _VENV_PYTHON, "dxa_to_wide_csv.py",
        "--text-source", "paddle_text",
        "--output", "data/paddle_wide_measurements.csv",
    ], dry=args.dry_run)
    return rc


def step_surya(args: argparse.Namespace) -> int:
    """Run Surya OCR on one or all patients."""
    patients = [args.patient] if args.patient else available_patients(Path("extracted_images"))
    if not patients:
        print("  No patients found for Surya.")
        return 1

    for pnum in patients:
        img_dir = Path("extracted_images") / f"Patient_{pnum}"
        if not img_dir.is_dir():
            print(f"  Skipping Patient {pnum}: no images found.")
            continue
        out_dir = Path("ocr_compare") / f"patient_{pnum}"
        print(f"\n\033[1m=== SURYA: Patient {pnum} ===\033[0m")
        rc = run([
            _VENV_PYTHON, "scripts/run_ocr_harness.py",
            "--input", str(img_dir),
            "--output", str(out_dir),
            "--python", _VENV_PYTHON,
            "--exts", "png",
        ], dry=args.dry_run)
        if rc != 0:
            print(f"  Surya failed for Patient {pnum} (continuing).")
    return 0


def step_compare(args: argparse.Namespace) -> int:
    """Generate backend comparison CSVs and markdown reports for all patients."""
    patients = [args.patient] if args.patient else available_patients(Path("ocr_compare"))
    if not patients:
        print("  No OCR compare data found.")
        return 1

    for pnum in patients:
        out_dir = Path("ocr_compare") / f"patient_{pnum}"
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n\033[1m=== COMPARE: Patient {pnum} ===\033[0m")
        rc = run([
            _VENV_PYTHON, "scripts/compare_ocr_backends.py",
            "--folder", pnum,
            "--out", str(out_dir / "compare_summary.csv"),
        ], dry=args.dry_run)
        if rc == 0:
            run([
                _VENV_PYTHON, "scripts/compare_csv_to_md.py",
                "--csv", str(out_dir / "compare_summary.csv"),
                "--out", str(out_dir / "compare_summary.md"),
            ], dry=args.dry_run)
        else:
            print(f"  compare_ocr_backends failed for Patient {pnum} (skipping).")
    return 0


def step_validate(args: argparse.Namespace) -> int:
    """Patient-by-patient validation: compare Tesseract vs Paddle BMD/T/Z values."""
    import pandas as pd

    tess_csv = Path("data/patient_wide_measurements.csv")
    paddle_csv = Path("data/paddle_wide_measurements.csv")

    if not tess_csv.exists():
        print("  Tesseract CSV not found. Run --step tesseract first.")
        return 1

    # Read as float-capable; missing values become NaN
    tess = pd.read_csv(tess_csv)
    has_paddle = paddle_csv.exists()
    paddle = pd.read_csv(paddle_csv) if has_paddle else pd.DataFrame()

    # Ensure Folder is string for reliable merge
    tess["Folder"] = tess["Folder"].astype(str)
    if has_paddle:
        paddle["Folder"] = paddle["Folder"].astype(str)

    # Columns to compare: (label, tess_col, paddle_col, tolerance)
    COMPARE_COLS: list[tuple[str, str, float]] = [
        # ── Spine L1‑L4 ──
        ("Spine BMD",          "Spine_L1L4_BMD",   0.05),
        ("Spine YA%",          "Spine_L1L4_YA",    5.0),
        ("Spine T",            "Spine_L1L4_T",     0.5),
        ("Spine AM%",          "Spine_L1L4_AM",    5.0),
        ("Spine Z",            "Spine_L1L4_Z",     0.5),
        ("Spine BMC",          "Spine_L1L4_BMC",   2.0),
        ("Spine Area",         "Spine_L1L4_Area",  2.0),
        # ── Left Femur Neck ──
        ("LFem Neck BMD",      "LFemur_Neck_BMD",  0.05),
        ("LFem Neck T",        "LFemur_Neck_T",    0.5),
        ("LFem Neck Z",        "LFemur_Neck_Z",    0.5),
        # ── Left Femur Total ──
        ("LFem Total BMD",     "LFemur_Total_BMD", 0.05),
        ("LFem Total T",       "LFemur_Total_T",   0.5),
        ("LFem Total Z",       "LFemur_Total_Z",   0.5),
        # ── Right Femur Neck ──
        ("RFem Neck BMD",      "RFemur_Neck_BMD",  0.05),
        ("RFem Neck T",        "RFemur_Neck_T",    0.5),
        # ── Right Femur Total ──
        ("RFem Total BMD",     "RFemur_Total_BMD", 0.05),
        ("RFem Total T",       "RFemur_Total_T",   0.5),
    ]

    lines: list[str] = []
    lines.append("# DXA Extraction Validation Report")
    lines.append("")
    lines.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("## Backend Comparison")
    lines.append("")
    lines.append("| # | Patient | Age | Spine BMD (T/P) | Spine T (T/P) | Spine Z (T/P) | LFem Total BMD (T/P) | LFem Total T (T/P) | Status |")
    lines.append("|---|---|---|---|---|---|---|---|---|")

    flags_surya: list[str] = []
    flags_sign: list[str] = []     # patients with likely sign errors in T‑scores
    ok_count = 0
    flagged_count = 0

    for _, trow in tess.iterrows():
        folder = str(trow["Folder"])
        name = str(trow.get("OCR_Name", ""))[:20]
        age  = trow.get("OCR_Age_years")

        prow = None
        if has_paddle:
            pm = paddle[paddle["Folder"] == folder]
            if not pm.empty:
                prow = pm.iloc[0]

        # ── Build display values ─────────────────────────────────────────
        def _disp(val) -> str:
            return f"{val:.3f}" if not pd.isna(val) else "—"

        spine_bmd = f"{_disp(trow.get('Spine_L1L4_BMD'))} / {_disp(prow.get('Spine_L1L4_BMD')) if prow is not None else '—'}"
        spine_t   = f"{_disp(trow.get('Spine_L1L4_T'))} / {_disp(prow.get('Spine_L1L4_T')) if prow is not None else '—'}"
        spine_z   = f"{_disp(trow.get('Spine_L1L4_Z'))} / {_disp(prow.get('Spine_L1L4_Z')) if prow is not None else '—'}"
        lfem_bmd  = f"{_disp(trow.get('LFemur_Total_BMD'))} / {_disp(prow.get('LFemur_Total_BMD')) if prow is not None else '—'}"
        lfem_t    = f"{_disp(trow.get('LFemur_Total_T'))} / {_disp(prow.get('LFemur_Total_T')) if prow is not None else '—'}"

        # ── Compare all columns ───────────────────────────────────────────
        all_ok = True
        any_tess_has = False
        any_paddle_has = False
        any_differs = False
        detail: list[str] = []

        for label, col, tol in COMPARE_COLS:
            tv = trow.get(col)
            pv = prow.get(col) if prow is not None else None
            tv_ok = not pd.isna(tv)
            pv_ok = not pd.isna(pv)
            if tv_ok:
                any_tess_has = True
            if pv_ok:
                any_paddle_has = True
            if tv_ok and pv_ok:
                diff = abs(float(tv) - float(pv))
                if diff > tol:
                    all_ok = False
                    any_differs = True
                    detail.append(f"{label}: {_disp(tv)} vs {_disp(pv)} (Δ={diff:.3f})")

        # ── Sign heuristics: flag positive T‑scores for patients ≥ 50 ─────
        age_val = float(age) if not pd.isna(age) else 0
        if age_val >= 50:
            for scol in ("Spine_L1L4_T", "LFemur_Neck_T", "LFemur_Total_T",
                         "RFemur_Neck_T", "RFemur_Total_T"):
                tv = trow.get(scol)
                pv = prow.get(scol) if prow is not None else None
                if not pd.isna(tv) and float(tv) > 0:
                    flags_sign.append(f"Patient {folder}: Tesseract {scol}={_disp(tv)} (positive — likely sign error)")
                if pv is not None and not pd.isna(pv) and float(pv) > 0:
                    flags_sign.append(f"Patient {folder}: Paddle {scol}={_disp(pv)} (positive — likely sign error)")

        # ── Status ────────────────────────────────────────────────────────
        if not any_tess_has and not any_paddle_has:
            status = "⚠️ BOTH MISSING"
            flagged_count += 1
            flags_surya.append(folder)
        elif any_tess_has and not any_paddle_has and has_paddle:
            status = "🟡 PADDLE MISSING"
            flagged_count += 1
            flags_surya.append(folder)
        elif any_paddle_has and not any_tess_has:
            status = "🟡 TESS MISSING"
            flagged_count += 1
        elif any_differs:
            status = f"🔴 MISMATCH ({'; '.join(detail[:3])})"  # limit detail to 3 items
            flagged_count += 1
            if not any_paddle_has and has_paddle:
                flags_surya.append(folder)
        else:
            status = "🟢 OK"
            ok_count += 1

        lines.append(f"| {folder} | {name} | {_disp(age)} | {spine_bmd} | {spine_t} | {spine_z} | {lfem_bmd} | {lfem_t} | {status} |")

    lines.append("")
    lines.append(f"**Summary:** {ok_count} OK, {flagged_count} flagged")
    if flags_sign:
        lines.append("")
        lines.append("## ⚠️ Possible Sign Errors")
        lines.append("")
        lines.append("The following T‑scores are positive for patients ≥ 50 years old — likely OCR sign‑loss errors:")
        lines.append("")
        for s in sorted(set(flags_sign)):
            lines.append(f"- {s}")
    if flags_surya:
        lines.append("")
        lines.append(f"**Patients where Paddle is missing (Surya fallback recommended):** {', '.join(flags_surya)}")
        lines.append("")
        lines.append("```bash")
        for p in flags_surya:
            lines.append(f"python scripts/run_full_pipeline.py --step surya --patient {p}")
        lines.append("```")

    out_path = Path("data/validation_report.md")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nValidation report: {out_path}")
    print(f"  {ok_count} patients OK, {flagged_count} flagged")
    if flags_surya:
        print(f"  Surya recommended for: Patients {', '.join(flags_surya)}")
    return 0


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="DXA Extraction Pipeline — Master Runner")
    parser.add_argument("--step", required=True,
                        choices=["tesseract", "paddle", "surya", "compare", "validate", "all"])
    parser.add_argument("--patient", default=None, help="Limit to patient folder N")
    parser.add_argument("--workers", type=int, default=1,
                        help="CPU workers for Paddle step (1 = single-process batch; >1 = parallel)")
    parser.add_argument("--skip-tesseract", action="store_true")
    parser.add_argument("--skip-paddle", action="store_true")
    parser.add_argument("--skip-surya", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    steps = [args.step] if args.step != "all" else ["tesseract", "paddle", "compare", "validate"]

    for step in steps:
        if step == "tesseract" and not args.skip_tesseract:
            rc = step_tesseract(args)
            if rc != 0:
                return rc
        elif step == "paddle" and not args.skip_paddle:
            rc = step_paddle(args)
            if rc != 0:
                return rc
        elif step == "surya" and not args.skip_surya:
            rc = step_surya(args)
            if rc != 0:
                print("Surya had errors (non-fatal).")
        elif step == "compare":
            step_compare(args)
        elif step == "validate":
            step_validate(args)

    print("\n\033[1;32mPipeline complete.\033[0m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
