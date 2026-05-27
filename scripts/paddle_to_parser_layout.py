#!/usr/bin/env python3
"""
Reorganize Paddle OCR .txt files into a layout compatible with dxa_to_wide_csv.py.

Paddle outputs:  ocr_compare/patient_N/paddle/<image>.png/<image>.txt
Parser expects:  <text_source>/Patient_N/<image>.txt

Usage: python scripts/paddle_to_parser_layout.py --paddle-dir ocr_compare --outdir paddle_text
"""
import argparse, os, shutil
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--paddle-dir', default='ocr_compare')
parser.add_argument('--outdir', default='paddle_text')
args = parser.parse_args()

out = Path(args.outdir)
if out.exists():
    shutil.rmtree(out)
out.mkdir(parents=True)

count = 0
paddle_base = Path(args.paddle_dir)

for patient_dir in sorted(paddle_base.iterdir()):
    if not patient_dir.is_dir() or not patient_dir.name.lower().startswith('patient_'):
        continue
    pnum = ''.join(c for c in patient_dir.name if c.isdigit())
    if not pnum:
        continue
    paddle_sub = patient_dir / 'paddle'
    if not paddle_sub.is_dir():
        continue

    target_dir = out / f'Patient_{pnum}'
    target_dir.mkdir(parents=True, exist_ok=True)

    for img_dir in sorted(paddle_sub.iterdir()):
        if not img_dir.is_dir():
            continue
        for txt_file in img_dir.glob('*.txt'):
            dest = target_dir / txt_file.name
            shutil.copy2(txt_file, dest)
            count += 1

print(f'Copied {count} text files to {out}/')
print(f'Now run: python dxa_to_wide_csv.py --text-source {out} --output data/paddle_wide_measurements.csv')
