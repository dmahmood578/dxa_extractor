#!/usr/bin/env python3
"""
Surya OCR wrapper script.

Usage:
  python scripts/surya_extract.py --check
  python scripts/surya_extract.py --image path/to/image.png --output output_folder

This script checks for Surya-related dependencies and runs a simple pipeline
to extract line-level text into a CSV.
"""

import sys
import os
import argparse
import shutil
import subprocess


def check_env():
    missing = []
    try:
        from PIL import Image  # noqa: F401
    except Exception:
        missing.append('pillow (PIL)')
    try:
        import torch  # noqa: F401
    except Exception:
        missing.append('torch')
    try:
        import surya  # noqa: F401
    except Exception:
        # package is often installed as surya-ocr; report the library name
        missing.append('surya-ocr')

    if missing:
        print('Missing modules:', ', '.join(missing))
        print('\nSuggested installs:')
        print('pip install pillow')
        print('pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu')
        print('pip install surya-ocr')
        return False
    print('All required modules appear available.')
    return True


def extract_surya(image_path, output_folder='output_surya'):
    from PIL import Image
    # tolerate different Surya import paths
    run_ocr = None
    load_det_model = None
    load_rec_model = None
    load_processor = None
    try:
        from surya.ocr import run_ocr as run_ocr  # noqa: F401
        from surya.model.detection.model import load_model as load_det_model  # noqa: F401
        from surya.model.recognition.model import load_model as load_rec_model  # noqa: F401
        from surya.model.recognition.processor import load_processor  # noqa: F401
    except Exception:
        try:
            # alternate import location
            import surya
            run_ocr = getattr(surya, 'run_ocr', None)
            # try to import submodules if available
            try:
                from surya.model.detection.model import load_model as load_det_model  # noqa: F401
                from surya.model.recognition.model import load_model as load_rec_model  # noqa: F401
                from surya.model.recognition.processor import load_processor  # noqa: F401
            except Exception:
                # leave as None and rely on surya.run_ocr wrapper if present
                pass
        except Exception:
            print('surya library not importable. Ensure surya-ocr is installed in this environment.')
            return

    if not os.path.exists(image_path):
        print(f"Image not found: {image_path}")
        return
    img = Image.open(image_path).convert('RGB')

    # If the high-level run_ocr function is available and accepts the simple API, use it.
    if run_ocr is not None and load_det_model is not None and load_rec_model is not None and load_processor is not None:
        print('Loading detection model...')
        det_model = load_det_model()
        print('Loading recognition model...')
        rec_model = load_rec_model()
        processor = load_processor()
        print('Running Surya OCR pipeline (may download model weights on first run)...')
        predictions = run_ocr([img], [["en"]], det_model, rec_model, processor)
    elif run_ocr is not None:
        print('Running Surya high-level run_ocr wrapper...')
        predictions = run_ocr([img], [["en"]])
    else:
        # Fallback: try to invoke the console script `surya_ocr` from the same
        # Python environment (sys.executable -> ../bin/surya_ocr)
        surya_exec = shutil.which('surya_ocr') or os.path.join(os.path.dirname(sys.executable), 'surya_ocr')
        if os.path.exists(surya_exec) and os.access(surya_exec, os.X_OK):
            print('Running Surya CLI:', surya_exec)
            try:
                # call surya_ocr to write its own results into output_folder
                cp = subprocess.run([surya_exec, '--output_dir', output_folder, image_path], capture_output=True, text=True)
                print('Surya CLI stdout:\n', cp.stdout)
                if cp.stderr:
                    print('Surya CLI stderr:\n', cp.stderr)
            except Exception as e:
                print('Failed to run surya_ocr CLI:', e)
                return

            # Surya writes a results.json file inside output_folder
            results_json = os.path.join(output_folder, 'results.json')
            if not os.path.exists(results_json):
                print('Surya CLI did not produce results.json in', output_folder)
                return
            import json
            import csv
            with open(results_json, 'r', encoding='utf-8') as f:
                data = json.load(f)

            os.makedirs(output_folder, exist_ok=True)
            out_csv = os.path.join(output_folder, 'surya_output.csv')
            with open(out_csv, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(['page', 'text', 'confidence'])
                # data is a mapping of input name -> list of page preds
                for name, pages in data.items():
                    for page in pages:
                        for line in page.get('text_lines', []):
                            if isinstance(line, dict):
                                text = line.get('text', '')
                                conf = line.get('confidence', '')
                            else:
                                text = getattr(line, 'text', '')
                                conf = getattr(line, 'confidence', '')
                            writer.writerow([page.get('page', ''), text, conf])

            print('Saved CSV:', out_csv)
            return
        else:
            print('No suitable Surya entrypoint found (run_ocr) and surya_ocr CLI not found.')
            return

    os.makedirs(output_folder, exist_ok=True)
    out_csv = os.path.join(output_folder, 'surya_output.csv')
    import csv
    with open(out_csv, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['page', 'text', 'confidence'])
        for p_idx, page in enumerate(predictions):
            for line in getattr(page, 'text_lines', []):
                text = getattr(line, 'text', '')
                conf = getattr(line, 'confidence', '')
                writer.writerow([p_idx, text, conf])

    print('Saved CSV:', out_csv)


def main():
    parser = argparse.ArgumentParser(description='Surya OCR wrapper')
    parser.add_argument('--check', action='store_true', help='Check environment')
    parser.add_argument('--image')
    parser.add_argument('--output', default='output_surya')
    args = parser.parse_args()
    if args.check:
        ok = check_env()
        if not ok:
            sys.exit(1)
        else:
            sys.exit(0)
    if not args.image:
        print('Provide --image or use --check')
        sys.exit(1)
    extract_surya(args.image, args.output)


if __name__ == '__main__':
    main()
