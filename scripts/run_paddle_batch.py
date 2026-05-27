#!/usr/bin/env python3
"""
Run PaddleOCR in a single process over all images to reuse model initialization.
Writes per-image TXT and JSON like `scripts/paddle_line_extract.py`.

Usage: python scripts/run_paddle_batch.py --input extracted_images --outdir ocr_compare --ext png --skip-existing
"""
import argparse, os, json, re, sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--input', default='extracted_images')
parser.add_argument('--outdir', default='ocr_compare')
parser.add_argument('--ext', default='png')
parser.add_argument('--skip-existing', action='store_true')
args = parser.parse_args()

from paddleocr import PaddleOCR
num_re = re.compile(r'(-?\d+\.\d+)')

print('Initializing PaddleOCR model (this may take a moment)')
ocr = PaddleOCR(use_angle_cls=True, lang='en')
print('Model initialized')

count=0
for root, dirs, files in os.walk(args.input):
    for fname in sorted(files):
        if not fname.lower().endswith('.' + args.ext.lower()):
            continue
        img_path = os.path.join(root, fname)
        # determine patient number from path: look for Patient_<n>
        parts = Path(root).parts
        patient_part = None
        for p in parts[::-1]:
            if p.lower().startswith('patient_'):
                patient_part = p
                break
        if patient_part is None:
            # fallback: use folder name
            patient_part = parts[-1]
        # normalize patient index
        pnum = ''.join([c for c in patient_part if c.isdigit()]) or patient_part
        out_base = os.path.join(args.outdir, f'patient_{pnum}', 'paddle', os.path.splitext(fname)[0] + '.png')
        os.makedirs(out_base, exist_ok=True)
        out_json = os.path.join(out_base, os.path.splitext(fname)[0] + '.json')
        out_txt = os.path.join(out_base, os.path.splitext(fname)[0] + '.txt')
        if args.skip_existing and os.path.exists(out_json):
            print('Skipping (exists):', img_path)
            continue
        try:
            res = None
            try:
                res = ocr.ocr(img_path)
            except TypeError:
                res = ocr.predict(img_path)
            # normalize lines
            lines = []
            if isinstance(res, dict):
                recs = res.get('rec_texts') or []
                lines.extend([t for t in recs if isinstance(t, str)])
            elif isinstance(res, list) and len(res) > 0 and isinstance(res[0], dict):
                for page in res:
                    recs = page.get('rec_texts') or []
                    lines.extend([t for t in recs if isinstance(t, str)])
            else:
                for item in res:
                    if isinstance(item, (list, tuple)) and len(item) >= 2:
                        candidate = item[1]
                        if isinstance(candidate, (list, tuple)) and len(candidate) > 0 and isinstance(candidate[0], str):
                            lines.append(candidate[0])
                        elif isinstance(candidate, str):
                            lines.append(candidate)
                    elif isinstance(item, str):
                        lines.append(item)
            # heuristics: collect candidates like paddle_line_extract
            candidates = []
            for i, line in enumerate(lines):
                low = line.lower()
                if any(k in low for k in ['neck', 'total', 'spine', 'l1', 'l2', 'l3', 'l4']):
                    window = ' '.join(lines[max(0, i-2):i+3])
                    m = num_re.search(window)
                    if m:
                        bmd = m.group(1)
                        try:
                            fval = float(bmd)
                            if not (0.1 <= fval <= 3.0):
                                continue
                        except Exception:
                            continue
                        mt = None
                        for tmatch in re.finditer(r'(-?\d+\.?\d*)', window):
                            tv = tmatch.group(1)
                            if tv != bmd and abs(float(tv)) <= 15:
                                mt = tv
                                break
                        if 'neck' in low:
                            region = 'Neck'
                        elif 'total' in low or 'l1' in low or 'spine' in low:
                            region = 'Spine'
                        else:
                            region = 'Unknown'
                        candidates.append({'region': region, 'bmd': bmd, 't': mt, 'line': line})
            # write outputs
            with open(out_txt,'w',encoding='utf-8') as f:
                f.write('\n'.join(lines))
            with open(out_json,'w',encoding='utf-8') as f:
                json.dump({'candidates': candidates, 'lines': lines}, f, indent=2)
            print('Processed', img_path)
            count += 1
        except Exception as e:
            print('Failed', img_path, e)

print('Done. Processed', count, 'images')
