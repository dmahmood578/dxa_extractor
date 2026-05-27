#!/usr/bin/env python3
"""
Simple PaddleOCR line extractor fallback.
Usage: python scripts/paddle_line_extract.py --image <image> --outdir <outdir>
Writes `<outdir>/<basename>.txt` with one OCR line per line.
"""
import argparse
import os

parser = argparse.ArgumentParser()
parser.add_argument('--image', required=True)
parser.add_argument('--outdir', required=True)
args = parser.parse_args()

from paddleocr import PaddleOCR
import json, re

ocr = PaddleOCR(use_angle_cls=True, lang='en')
# call API without deprecated 'cls' kwarg
try:
    res = ocr.ocr(args.image)
except TypeError:
    res = ocr.predict(args.image)

lines = []
# Normalize to simple list of strings
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

# Basic heuristics: collect candidate region rows from OCR lines
candidate_decimal_re = re.compile(r'(-?\d+\.\d+)')
candidate_number_re = re.compile(r'(-?\d+\.?\d*)')
candidates = []
for i, line in enumerate(lines):
    low = line.lower()
    # look for region keywords
    if any(k in low for k in ['neck', 'total', 'spine', 'l1', 'l2', 'l3', 'l4']):
        window_lines = lines[max(0, i-2):i+3]
        window = ' '.join(window_lines)
        # prefer decimal numbers as BMD; fall back to small integers when safe
        m = candidate_decimal_re.search(window)
        if not m:
            # accept integer-like numbers only if they are plausible and not dates/years
            for nm in candidate_number_re.finditer(window):
                val = nm.group(1)
                # skip long integers (years) and slashes
                if '/' in window or len(val) >= 5:
                    continue
                # prefer numbers between 0 and 4
                try:
                    fv = float(val)
                    if 0.1 <= fv <= 3.0:
                        m = nm
                        break
                except Exception:
                    continue
        if m:
            bmd = m.group(1)
            # sanity: BMD plausible range
            try:
                f = float(bmd)
                if not (0.1 <= f <= 3.0):
                    continue
            except Exception:
                continue
            # find T-score nearby (prefer negative numbers or numbers with magnitude <=15)
            mt = None
            for tmatch in candidate_number_re.finditer(window):
                tv = tmatch.group(1)
                if tv == bmd:
                    continue
                try:
                    ft = float(tv)
                    if abs(ft) <= 15:
                        mt = tv
                        # prefer negative/decimal T-scores
                        if ft < 0 or ('.' in tv):
                            break
                except Exception:
                    continue
            # map region with left/right disambiguation
            region = 'Unknown'
            if 'neck' in low:
                if any(w in low for w in ['left', 'l ', ' l.', 'lt', 'l-']):
                    region = 'Left_Neck'
                elif any(w in low for w in ['right', 'r ', 'rt', 'r-']):
                    region = 'Right_Neck'
                else:
                    # check nearby lines for left/right hints
                    joined = ' '.join(window_lines).lower()
                    if 'left' in joined:
                        region = 'Left_Neck'
                    elif 'right' in joined:
                        region = 'Right_Neck'
                    else:
                        region = 'Neck'
            elif 'total' in low or 'l1' in low or 'spine' in low:
                region = 'Spine'
            candidates.append({'region': region, 'bmd': bmd, 't': mt, 'line': line})

# ensure outdir
os.makedirs(args.outdir, exist_ok=True)
bname = os.path.splitext(os.path.basename(args.image))[0]
out_txt = os.path.join(args.outdir, bname + '.txt')
out_json = os.path.join(args.outdir, bname + '.json')
with open(out_txt, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
with open(out_json, 'w', encoding='utf-8') as f:
    json.dump({'candidates': candidates, 'lines': lines}, f, indent=2)
print('Wrote', out_txt)
print('Wrote', out_json)
