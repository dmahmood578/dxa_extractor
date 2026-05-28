import os
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pydicom
from PIL import Image, ImageFilter, ImageOps

TESSERACT_PATH = "tesseract"
TESSERACT_NUMERIC_WHITELIST = "0123456789.,-+()%[]/:|"

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PARENT_DIR = os.path.dirname(_SCRIPT_DIR)
CLD_DXA_DIR = os.path.join(_PARENT_DIR, "CLD DXA")
EXTRACTED_IMAGES_DIR = os.path.join(_SCRIPT_DIR, "extracted_images")
EXTRACTED_TEXT_DIR = os.path.join(_SCRIPT_DIR, "extracted_text")
EXTRACTED_FIGURES_DIR = os.path.join(_SCRIPT_DIR, "extracted_figures")

REGION_DEFS = [
    {"name": "header", "box": (0.05, 0.07, 0.95, 0.24), "psm": 6},
    {"name": "ap_spine", "box": (0.58, 0.17, 0.97, 0.37), "psm": 6},
    {"name": "left_femur", "box": (0.58, 0.39, 0.97, 0.52), "psm": 6},
    {"name": "dual_femur", "box": (0.54, 0.39, 0.97, 0.55), "psm": 6},
    {"name": "tbs", "box": (0.46, 0.59, 0.97, 0.69), "psm": 6},
    {"name": "trend", "box": (0.38, 0.73, 0.97, 0.87), "psm": 6},
]


def _scale_to_uint8(arr):
    arr_min, arr_max = arr.min(), arr.max()
    if arr_max > arr_min:
        return ((arr - arr_min) / (arr_max - arr_min) * 255.0).astype(np.uint8)
    return arr.astype(np.uint8)


def _dicom_to_image(ds):
    arr = ds.pixel_array
    photo_interp = getattr(ds, "PhotometricInterpretation", "MONOCHROME2")

    if photo_interp == "PALETTE COLOR":
        from pydicom.pixel_data_handlers.util import apply_color_lut

        rgb_arr = apply_color_lut(arr, ds)
        if rgb_arr.dtype == np.uint16:
            return Image.fromarray((rgb_arr // 256).astype(np.uint8))
        return Image.fromarray(rgb_arr.astype(np.uint8))

    if len(arr.shape) == 3:
        return Image.fromarray(arr)

    return Image.fromarray(_scale_to_uint8(arr))


def _clean_label(label):
    label = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    return label or "figure"


def infer_scan_label(metadata, ocr_text):
    haystack = " ".join(
        str(metadata.get(key, "") or "")
        for key in ("series_description", "protocol_name", "body_part_examined")
    )
    haystack = f"{haystack} {ocr_text or ''}".lower()

    label_rules = [
        ("left_hip", [r"left\s+femur", r"left\s+hip", r"lt\s+hip", r"lfemur"]),
        ("right_hip", [r"right\s+femur", r"right\s+hip", r"rt\s+hip", r"rfemur"]),
        ("spine", [r"ap\s+spine", r"l1\s*[-–]\s*l4", r"lumbar\s+spine", r"spine\s+bone\s+density"]),
        ("dual_femur", [r"dual\s*femur", r"dualfemur"]),
        ("whole_body", [r"whole\s+body", r"total\s+body"]),
        ("hip", [r"hip"]),
    ]

    for label, patterns in label_rules:
        if any(re.search(pattern, haystack) for pattern in patterns):
            return label
    return "figure"


def crop_scan_figure(img):
    width, height = img.size
    left = int(width * 0.04)
    top = int(height * 0.15)
    right = int(width * 0.48)
    bottom = int(height * 0.56)
    return img.crop((left, top, right, bottom))


def crop_region(img, box):
    width, height = img.size
    left, top, right, bottom = box
    return img.crop((
        int(width * left),
        int(height * top),
        int(width * right),
        int(height * bottom),
    ))


def _prepare_ocr_image(img, numeric=False):
    prepared = ImageOps.grayscale(img)
    prepared = ImageOps.autocontrast(prepared)
    prepared = prepared.filter(ImageFilter.SHARPEN)

    if min(prepared.size) < 1400:
        scale = max(2, int(round(1400 / max(1, min(prepared.size)))))
        prepared = prepared.resize(
            (prepared.size[0] * scale, prepared.size[1] * scale),
            Image.Resampling.LANCZOS,
        )

    if numeric:
        prepared = prepared.filter(ImageFilter.MedianFilter(size=3))
        prepared = prepared.point(lambda px: 255 if px > 185 else 0)

    return prepared


def _tesseract_text_from_image(img, psm=6, numeric=False):
    config = ["--oem", "1", "--psm", str(psm), "-c", "preserve_interword_spaces=1"]
    if numeric:
        config.extend(["-c", f"tessedit_char_whitelist={TESSERACT_NUMERIC_WHITELIST}"])

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        _prepare_ocr_image(img, numeric=numeric).save(tmp_path)
        cmd = [TESSERACT_PATH, tmp_path, "stdout", *config]
        cp = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
        return (cp.stdout or "").strip()
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def run_tesseract(image_path, txt_output_path_base, psm=None, numeric=False):
    try:
        img = Image.open(image_path).convert("RGB")
    except Exception:
        return None

    text = _tesseract_text_from_image(img, psm=psm or (11 if numeric else 6), numeric=numeric)
    txt_path = f"{txt_output_path_base}.txt"
    with open(txt_path, "w", encoding="utf-8") as handle:
        handle.write(text)
        if text and not text.endswith("\n"):
            handle.write("\n")
    return txt_path


def save_region_ocr(image_path, patient_txt_dir, base_name, region_def):
    try:
        img = Image.open(image_path)
    except Exception:
        return None

    region_img = crop_region(img, region_def["box"])
    if min(region_img.size) < 900:
        region_img = region_img.resize((region_img.size[0] * 2, region_img.size[1] * 2))
    region_base = f"{base_name}_{region_def['name']}"
    region_img_path = os.path.join(patient_txt_dir, f"{region_base}.png")
    region_txt_base = os.path.join(patient_txt_dir, region_base)
    region_img.save(region_img_path)
    run_tesseract(region_img_path, region_txt_base, psm=region_def.get("psm", 6), numeric=True)
    return region_txt_base + ".txt"


def process_dicom_file(dicom_path, patient_img_dir):
    try:
        ds = pydicom.dcmread(dicom_path)
        if not hasattr(ds, "PixelData"):
            return None

        image = _dicom_to_image(ds)
        series_num = getattr(ds, "SeriesNumber", "UNKNOWN")
        inst_num = getattr(ds, "InstanceNumber", "UNKNOWN")

        out_filename = f"ser_{series_num}_inst_{inst_num}.png"
        out_path = os.path.join(patient_img_dir, out_filename)
        image.save(out_path)

        return {
            "image_path": out_path,
            "series_num": series_num,
            "inst_num": inst_num,
            "series_description": getattr(ds, "SeriesDescription", ""),
            "protocol_name": getattr(ds, "ProtocolName", ""),
            "body_part_examined": getattr(ds, "BodyPartExamined", ""),
        }
    except Exception:
        return None


def save_figure_crop(image_path, figure_dir, metadata, ocr_text=""):
    try:
        img = Image.open(image_path)
    except Exception:
        return None

    label = infer_scan_label(metadata, ocr_text)
    cropped = crop_scan_figure(img)

    base_name = os.path.splitext(os.path.basename(image_path))[0]
    out_filename = f"{base_name}_{_clean_label(label)}.png"
    out_path = os.path.join(figure_dir, out_filename)
    cropped.save(out_path)
    return out_path


def process_patient_folder(folder):
    folder_path = os.path.join(CLD_DXA_DIR, folder)
    if not os.path.isdir(folder_path):
        return

    anonymized_id = f"ANON_{folder}"
    for root, _, files in os.walk(folder_path):
        for filename in files:
            if filename.startswith(".") or filename.upper() == "DICOMDIR":
                continue
            try:
                ds = pydicom.dcmread(os.path.join(root, filename), stop_before_pixels=True)
                anonymized_id = getattr(ds, "PatientID", f"ANON_{folder}")
                break
            except Exception:
                pass
        if anonymized_id:
            break

    print(f"\nProcessing Folder {folder} (ID: {anonymized_id})...")

    patient_img_dir = os.path.join(EXTRACTED_IMAGES_DIR, f"Patient_{folder}")
    patient_txt_dir = os.path.join(EXTRACTED_TEXT_DIR, f"Patient_{folder}")
    patient_fig_dir = os.path.join(EXTRACTED_FIGURES_DIR, f"Patient_{folder}")
    os.makedirs(patient_img_dir, exist_ok=True)
    os.makedirs(patient_txt_dir, exist_ok=True)
    os.makedirs(patient_fig_dir, exist_ok=True)

    dicom_files = []
    for root, _, files in os.walk(folder_path):
        for filename in files:
            if filename.startswith(".") or filename.upper() == "DICOMDIR":
                continue
            dicom_files.append(os.path.join(root, filename))

    extracted_images = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(process_dicom_file, path, patient_img_dir) for path in dicom_files]
        for fut in futures:
            result = fut.result()
            if result:
                extracted_images.append(result)

    print(f"  Extracted {len(extracted_images)} images for Folder {folder}.")

    ocr_count = 0
    figure_count = 0
    region_count = 0
    for image_info in extracted_images:
        img_path = image_info["image_path"]
        base_name = os.path.splitext(os.path.basename(img_path))[0]
        txt_output_path_base = os.path.join(patient_txt_dir, base_name)

        try:
            run_tesseract(img_path, txt_output_path_base)
            ocr_count += 1

            txt_path = f"{txt_output_path_base}.txt"
            ocr_text = ""
            if os.path.exists(txt_path):
                with open(txt_path, encoding="utf-8", errors="replace") as handle:
                    ocr_text = handle.read()

            for region_def in REGION_DEFS:
                region_txt_path = save_region_ocr(img_path, patient_txt_dir, base_name, region_def)
                if region_txt_path and os.path.exists(region_txt_path):
                    region_count += 1

            figure_path = save_figure_crop(img_path, patient_fig_dir, image_info, ocr_text)
            if figure_path:
                figure_count += 1
                print(f"  Saved figure crop: {figure_path}")
                figure_txt_base = os.path.splitext(figure_path)[0]
                run_tesseract(figure_path, figure_txt_base, psm=6, numeric=False)
                run_tesseract(figure_path, f"{figure_txt_base}.numeric", psm=11, numeric=True)
        except Exception as exc:
            print(f"  OCR failed for {img_path}: {exc}")

    print(f"  Completed OCR on {ocr_count} images for Folder {folder}.")
    print(f"  Saved {region_count} region OCR files for Folder {folder}.")
    print(f"  Saved {figure_count} figure crops for Folder {folder}.")


def main():
    folders = sorted(
        [folder for folder in os.listdir(CLD_DXA_DIR) if os.path.isdir(os.path.join(CLD_DXA_DIR, folder))],
        key=lambda value: int(value) if value.isdigit() else 999,
    )

    print(f"Found {len(folders)} patient folders to process: {folders}")

    for folder in folders:
        process_patient_folder(folder)

    print("\nAll patient images and text extracted successfully!")


if __name__ == "__main__":
    main()
