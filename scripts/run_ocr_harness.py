#!/usr/bin/env python3
"""
Run both Paddle PP-Structure and Surya OCR on all images in a folder.

Produces a CSV summary at <output_dir>/summary.csv and per-image logs at
<output_dir>/logs/. Uses the Python interpreter that runs this script by
default (so activate the desired venv first).

Example:
  python scripts/run_ocr_harness.py --input data/images --output ocr_results

"""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
import time
from pathlib import Path


def find_images(input_dir: Path, exts, recursive: bool = True):
    patterns = [f"**/*.{e}" if recursive else f"*.{e}" for e in exts]
    files = []
    for p in patterns:
        files.extend(input_dir.glob(p))
    files = [f for f in files if f.is_file()]
    return sorted(files)


def safe_name(path: Path, base: Path) -> str:
    try:
        rel = path.relative_to(base)
    except Exception:
        rel = Path(path.name)
    # use double-underscore for path separators to avoid collisions
    return str(rel).replace(os.sep, '__')


def run_script(python_exe: str, script_path: str, image_path: Path, out_dir: str):
    cmd = [python_exe, script_path, '--image', str(image_path), '--output', out_dir]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def main():
    p = argparse.ArgumentParser(description='Run Paddle PP-Structure + Surya on a folder')
    p.add_argument('--input', '-i', required=True, help='Input folder to scan for images')
    p.add_argument('--output', '-o', default='ocr_results', help='Output base folder')
    p.add_argument('--python', default=sys.executable, help='Python executable to run the helper scripts')
    p.add_argument('--paddle-script', default='scripts/paddle_ppstructure_extract.py', help='Path to Paddle extractor script')
    p.add_argument('--surya-script', default='scripts/surya_extract.py', help='Path to Surya extractor script')
    p.add_argument('--exts', default='png,jpg,jpeg,tif,tiff,bmp', help='Comma-separated image extensions')
    p.add_argument('--no-recursive', dest='recursive', action='store_false', help='Do not search recursively')
    p.add_argument('--dry-run', action='store_true', help='Show actions but do not execute')
    args = p.parse_args()

    input_dir = Path(args.input).expanduser().resolve()
    output_dir = Path(args.output).expanduser().resolve()
    python_exe = args.python
    paddle_script = args.paddle_script
    surya_script = args.surya_script
    exts = [e.strip().lstrip('*.') for e in args.exts.split(',') if e.strip()]

    if not input_dir.exists() or not input_dir.is_dir():
        print('Input folder not found:', input_dir)
        raise SystemExit(1)

    images = find_images(input_dir, exts, recursive=args.recursive)
    if not images:
        print('No images found in', input_dir)
        raise SystemExit(0)

    os.makedirs(output_dir, exist_ok=True)
    log_dir = output_dir / 'logs'
    log_dir.mkdir(exist_ok=True)

    summary_path = output_dir / 'summary.csv'
    fieldnames = [
        'image', 'paddle_rc', 'paddle_time', 'paddle_out', 'paddle_log',
        'surya_rc', 'surya_time', 'surya_out', 'surya_log', 'total_time'
    ]

    with open(summary_path, 'w', newline='', encoding='utf-8') as csvf:
        writer = csv.DictWriter(csvf, fieldnames=fieldnames)
        writer.writeheader()

        for img in images:
            print('\nProcessing:', img)
            safe = safe_name(img, input_dir)
            paddle_out = str(output_dir / 'paddle' / safe)
            surya_out = str(output_dir / 'surya' / safe)
            os.makedirs(paddle_out, exist_ok=True)
            os.makedirs(surya_out, exist_ok=True)

            paddle_log = str(log_dir / f'{safe}_paddle.log')
            surya_log = str(log_dir / f'{safe}_surya.log')

            row = {'image': str(img), 'paddle_out': paddle_out, 'surya_out': surya_out}

            if args.dry_run:
                print('DRY RUN: would run:', python_exe, paddle_script, '--image', img, '--output', paddle_out)
                print('DRY RUN: would run:', python_exe, surya_script, '--image', img, '--output', surya_out)
                row.update({'paddle_rc': 'dry', 'surya_rc': 'dry', 'paddle_time': 0, 'surya_time': 0, 'total_time': 0, 'paddle_log': '', 'surya_log': ''})
                writer.writerow(row)
                continue

            t0 = time.time()
            rc_p, out_p, err_p = run_script(python_exe, paddle_script, img, paddle_out)
            t1 = time.time()
            with open(paddle_log, 'w', encoding='utf-8') as lf:
                lf.write('STDOUT:\n')
                lf.write(out_p or '')
                lf.write('\n\nSTDERR:\n')
                lf.write(err_p or '')

            rc_s, out_s, err_s = run_script(python_exe, surya_script, img, surya_out)
            t2 = time.time()
            with open(surya_log, 'w', encoding='utf-8') as lf:
                lf.write('STDOUT:\n')
                lf.write(out_s or '')
                lf.write('\n\nSTDERR:\n')
                lf.write(err_s or '')

            row.update({
                'paddle_rc': rc_p,
                'paddle_time': round(t1 - t0, 3),
                'paddle_log': paddle_log,
                'surya_rc': rc_s,
                'surya_time': round(t2 - t1, 3),
                'surya_log': surya_log,
                'total_time': round(t2 - t0, 3),
            })

            writer.writerow(row)
            csvf.flush()
            print('Wrote logs:', paddle_log, surya_log)

    print('\nDone. Summary:', summary_path)


if __name__ == '__main__':
    main()
