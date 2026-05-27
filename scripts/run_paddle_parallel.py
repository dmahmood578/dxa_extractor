#!/usr/bin/env python3
"""
Run PaddleOCR over all images using N worker processes.
Each worker initializes PaddleOCR once and processes a partition of images.

Usage: python scripts/run_paddle_parallel.py --input extracted_images --outdir ocr_compare --workers 4 --skip-existing
"""
import argparse, os, json, re, sys, multiprocessing, traceback
from pathlib import Path

def process_partition(worker_id, img_paths, outdir, skip_existing):
    """Worker: init PaddleOCR once, then OCR all assigned images."""
    import warnings
    warnings.filterwarnings('ignore')
    from paddleocr import PaddleOCR

    num_re = re.compile(r'(-?\d+\.\d+)')
    ok = 0
    fail = 0
    skip = 0

    try:
        ocr = PaddleOCR(use_angle_cls=True, lang='en')
    except Exception as e:
        sys.stderr.write(f'[worker {worker_id}] PaddleOCR init failed: {e}\n')
        return 0, len(img_paths)

    for img_path in img_paths:
        # determine patient number from path
        parts = Path(img_path).parts
        patient_part = None
        for p in parts[::-1]:
            if p.lower().startswith('patient_'):
                patient_part = p
                break
        if patient_part is None:
            patient_part = parts[-1]
        pnum = ''.join([c for c in patient_part if c.isdigit()]) or patient_part

        fname = os.path.basename(img_path)
        base_name = os.path.splitext(fname)[0]
        out_base = os.path.join(outdir, f'patient_{pnum}', 'paddle', base_name + '.png')
        os.makedirs(out_base, exist_ok=True)
        out_json = os.path.join(out_base, base_name + '.json')
        out_txt = os.path.join(out_base, base_name + '.txt')

        if skip_existing and os.path.exists(out_json):
            skip += 1
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

            # heuristics: collect candidates
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

            with open(out_txt, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            with open(out_json, 'w', encoding='utf-8') as f:
                json.dump({'candidates': candidates, 'lines': lines}, f, indent=2)

            ok += 1
        except Exception as e:
            fail += 1
            sys.stderr.write(f'[worker {worker_id}] Failed {img_path}: {e}\n')

    return ok, fail, skip


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', default='extracted_images')
    parser.add_argument('--outdir', default='ocr_compare')
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--ext', default='png')
    parser.add_argument('--skip-existing', action='store_true')
    args = parser.parse_args()

    # collect all image paths
    all_images = []
    for root, dirs, files in os.walk(args.input):
        for fname in sorted(files):
            if fname.lower().endswith('.' + args.ext.lower()):
                all_images.append(os.path.join(root, fname))

    if not all_images:
        print('No images found')
        return

    n = len(all_images)
    nw = min(args.workers, n)
    print(f'Found {n} images, using {nw} workers')

    # partition images across workers
    partitions = [[] for _ in range(nw)]
    for i, img in enumerate(all_images):
        partitions[i % nw].append(img)

    # launch workers
    ctx = multiprocessing.get_context('spawn')
    procs = []
    for wid in range(nw):
        p = ctx.Process(target=process_partition, args=(wid, partitions[wid], args.outdir, args.skip_existing))
        p.start()
        procs.append(p)

    total_ok = 0
    total_fail = 0
    total_skip = 0
    for wid, p in enumerate(procs):
        p.join()
        # result from worker is not easily retrievable via Process; workers print status
    # workers print their own counts; aggregate from output not trivial, so estimate from exit
    print(f'\nAll {nw} workers finished.')
    print(f'Outputs written under {args.outdir}/patient_<n>/paddle/')


if __name__ == '__main__':
    main()
