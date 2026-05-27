#!/usr/bin/env python3
"""
Extract PNG images from all DICOM files found under an input folder.

Usage:
  python scripts/extract_dicom_folder.py --input "/path/to/CLD DXA" --output ocr_input_cld_dxa

The script walks the input folder recursively, attempts to read each file
with pydicom, and saves any pixel-containing file as a PNG in the output
folder. Filenames include patient/series/instance when available.
"""

import argparse
import os
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description='Extract PNGs from DICOM files')
    parser.add_argument('--input', '-i', required=True, help='Input folder to scan for DICOMs')
    parser.add_argument('--output', '-o', default='ocr_input', help='Output folder for extracted PNGs')
    args = parser.parse_args()

    input_dir = Path(args.input).expanduser().resolve()
    output_dir = Path(args.output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        import pydicom
        from PIL import Image
        import numpy as np
    except Exception as e:
        print('Missing dependency:', e)
        print('Install pydicom and pillow in your venv and retry.')
        raise SystemExit(1)

    extracted = 0
    skipped = 0
    for root, dirs, files in os.walk(input_dir):
        for fname in files:
            if fname.startswith('.'):
                continue
            path = Path(root) / fname
            try:
                ds = pydicom.dcmread(str(path), force=True)
            except Exception:
                skipped += 1
                continue

            if not hasattr(ds, 'PixelData'):
                skipped += 1
                continue

            try:
                arr = ds.pixel_array
            except Exception:
                skipped += 1
                continue

            # handle palette color
            photo_interp = getattr(ds, 'PhotometricInterpretation', 'UNKNOWN')
            try:
                if photo_interp == 'PALETTE COLOR':
                    from pydicom.pixel_data_handlers.util import apply_color_lut
                    rgb = apply_color_lut(arr, ds)
                    if rgb.dtype == np.uint16:
                        img = Image.fromarray((rgb // 256).astype('uint8'))
                    else:
                        img = Image.fromarray(rgb.astype('uint8'))
                elif arr.ndim == 3 and arr.shape[0] in (3, 4):
                    # channel-first RGB
                    img = Image.fromarray(arr.transpose(1, 2, 0))
                elif arr.ndim == 3 and arr.shape[-1] in (3, 4):
                    img = Image.fromarray(arr)
                else:
                    # grayscale: scale to 0-255
                    a = arr
                    amin, amax = a.min(), a.max()
                    if amax > amin:
                        a = ((a - amin) / (amax - amin) * 255.0).astype('uint8')
                    else:
                        a = a.astype('uint8')
                    img = Image.fromarray(a)
            except Exception as e:
                skipped += 1
                continue

            patient = getattr(ds, 'PatientID', None) or 'UNKNOWN'
            modality = getattr(ds, 'Modality', None) or 'UNK'
            series = getattr(ds, 'SeriesNumber', None) or '0'
            inst = getattr(ds, 'InstanceNumber', None) or extracted

            out_name = f"pat_{patient}_mod_{modality}_ser_{series}_inst_{inst}.png"
            out_path = output_dir / out_name
            try:
                img.save(str(out_path))
                extracted += 1
                print('Saved:', out_path)
            except Exception:
                skipped += 1

    print(f"Finished. Extracted {extracted} images, skipped {skipped} files.")

if __name__ == '__main__':
    main()
