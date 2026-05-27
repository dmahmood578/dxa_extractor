#!/usr/bin/env python3
"""
PaddleOCR + PP-Structure table extractor helper.

Usage:
  python scripts/paddle_ppstructure_extract.py --check
  python scripts/paddle_ppstructure_extract.py --image path/to/image.png --output output_folder

This script is a lightweight wrapper that checks for required packages and
runs PP-Structure to extract HTML tables, then attempts to convert them to Excel.
"""

import sys
import os
import argparse


def check_env():
    missing = []
    tips = {}
    try:
        import cv2  # noqa: F401
    except Exception:
        missing.append('opencv-python (cv2)')
        tips['opencv-python (cv2)'] = 'pip install opencv-python'

    # Only check that paddleocr is importable; the internal class name varies
    try:
        import paddleocr as _paddleocr  # noqa: F401
    except Exception:
        missing.append('paddleocr')
        tips['paddleocr'] = 'pip install paddleocr  # ensure paddlepaddle is installed first'

    try:
        import pandas as pd  # noqa: F401
    except Exception:
        missing.append('pandas')
        tips['pandas'] = 'pip install pandas lxml'
    try:
        import numpy as np  # noqa: F401
    except Exception:
        missing.append('numpy')
        tips['numpy'] = 'pip install numpy'

    print('\nEnvironment check for PaddleOCR + PP-Structure:')
    if missing:
        print('\nMissing modules:')
        for m in missing:
            print(f"- {m}: {tips.get(m, '')}")
        print('\nSuggested combined install (may still require paddlepaddle):')
        print('pip install paddleocr pandas opencv-python pillow')
        print("If you need paddlepaddle (CPU): pip install paddlepaddle")
        return False
    else:
        print('All required modules appear available (paddleocr may expose different class names).')
        return True


def extract_table(image_path, output_folder='output_tables', lang='en'):
    import cv2
    import pandas as pd

    # Import PP-Structure class from paddleocr using tolerant fallbacks
    PPStructure = None
    try:
        from paddleocr import PPStructure as PPStructure  # noqa: F401
    except Exception:
        try:
            from paddleocr import PPStructureV3 as PPStructure  # noqa: F401
        except Exception:
            try:
                from paddleocr import PPStructureV2 as PPStructure  # noqa: F401
            except Exception:
                try:
                    import paddleocr as _paddleocr
                    PPStructure = getattr(_paddleocr, 'PPStructure', None) or getattr(_paddleocr, 'PPStructureV3', None) or getattr(_paddleocr, 'PPStructureV2', None)
                except Exception:
                    PPStructure = None

    if PPStructure is None:
        print('paddleocr is installed but PPStructure class was not found. Check installed paddleocr version and available classes.')
        return

    if not os.path.exists(image_path):
        print(f"Image not found: {image_path}")
        return
    img = cv2.imread(image_path)
    if img is None:
        print('Failed to read image (cv2 returned None). Is the path correct?')
        return

    # Initialize PPStructure with a tolerant sequence of possible signatures
    engine = None
    init_attempts = []
    init_errors = []
    try_options = [
        {'show_log': False, 'table': True, 'lang': lang},
        {'show_log': False, 'lang': lang},
        {'lang': lang, 'use_table_recognition': True},
        {'lang': lang},
        {},
    ]
    for opts in try_options:
        try:
            engine = PPStructure(**opts)
            init_attempts.append(opts)
            break
        except Exception as e:
            init_errors.append((opts, e))

    if engine is None:
        print('Could not initialize PPStructure with any known signature. Tried:')
        for opts, err in init_errors:
            print(f"  opts={opts} -> {err}")
        return

    try:
        result = engine(img)
    except Exception as e:
        print('Error running PP-Structure on image:', e)
        return

    os.makedirs(output_folder, exist_ok=True)
    # Normalize result into an iterable of region-like items
    def _to_regions(res):
        regions = []
        if res is None:
            return regions
        if isinstance(res, dict):
            # value may be a list of regions or a single region dict
            for v in res.values():
                if isinstance(v, list):
                    regions.extend(v)
                elif isinstance(v, dict):
                    regions.append(v)
                else:
                    regions.append(v)
            return regions
        if isinstance(res, (list, tuple)):
            regions.extend(res)
            return regions
        # fallback: single object
        return [res]

    regions = _to_regions(result)
    count = 0

    def _extract_html_from_region(region):
        # Try common dict/object shapes first
        html = None
        rtype = None
        try:
            if isinstance(region, dict):
                rtype = region.get('type') or region.get('label')
                res_field = region.get('res')
                if isinstance(res_field, dict):
                    html = res_field.get('html') or res_field.get('html_string')
                if not html:
                    html = region.get('html') or region.get('res')
            else:
                # object-like
                if hasattr(region, 'model_dump'):
                    rd = region.model_dump()
                    if isinstance(rd, dict):
                        rtype = rd.get('type') or rd.get('label')
                        res_field = rd.get('res')
                        if isinstance(res_field, dict):
                            html = res_field.get('html') or res_field.get('html_string')
                if not html:
                    rtype = rtype or getattr(region, 'type', None) or getattr(region, 'label', None)
                    html = getattr(region, 'html', None) or getattr(region, 'res', None)
        except Exception:
            html = None
            rtype = None

        # Fallback: stringify and search for HTML table
        if not html:
            s = str(region)
            idx = s.find('<table')
            if idx != -1:
                j = s.rfind('</table>')
                if j != -1:
                    html = s[idx:j + len('</table>')]
        return rtype, html

    for i, region in enumerate(regions):
        rtype, html = _extract_html_from_region(region)
        if not html:
            continue
        # Only treat as table if type indicates table or HTML contains a table
        if rtype and 'table' not in str(rtype).lower() and '<table' not in html.lower():
            continue
        html_path = os.path.join(output_folder, f"extracted_table_{count}.html")
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"Saved table HTML: {html_path}")
        # attempt convert to Excel
        try:
            dfs = pd.read_html(html_path)
            if dfs:
                df = dfs[0]
                excel_path = os.path.join(output_folder, f"extracted_table_{count}.xlsx")
                df.to_excel(excel_path, index=False)
                print(f"Saved Excel: {excel_path}")
        except Exception as e:
            print('Could not convert HTML to Excel:', e)
        count += 1

    if count == 0:
        print('No tables detected by PP-Structure.')


def main():
    parser = argparse.ArgumentParser(description='PaddleOCR PP-Structure table extractor')
    parser.add_argument('--check', action='store_true', help='Check environment imports and exit')
    parser.add_argument('--image', help='Path to image file')
    parser.add_argument('--output', default='output_tables', help='Output folder')
    parser.add_argument('--lang', default='en', help='Language code for OCR')
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

    extract_table(args.image, args.output, args.lang)


if __name__ == '__main__':
    main()
