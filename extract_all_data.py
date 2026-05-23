import os
import pydicom
import subprocess
from PIL import Image
import numpy as np
from concurrent.futures import ThreadPoolExecutor

TESSERACT_PATH = 'tesseract'

def process_dicom_file(dicom_path, patient_img_dir):
    try:
        ds = pydicom.dcmread(dicom_path)
        if not hasattr(ds, 'PixelData'):
            return None
            
        modality = getattr(ds, 'Modality', 'UNKNOWN')
        series_num = getattr(ds, 'SeriesNumber', 'UNKNOWN')
        inst_num = getattr(ds, 'InstanceNumber', 'UNKNOWN')
        photo_interp = getattr(ds, 'PhotometricInterpretation', 'MONOCHROME2')
        
        arr = ds.pixel_array
        
        # Scale and convert pixel array
        if photo_interp == 'PALETTE COLOR':
            from pydicom.pixel_data_handlers.util import apply_color_lut
            rgb_arr = apply_color_lut(arr, ds)
            if rgb_arr.dtype == np.uint16:
                img = Image.fromarray((rgb_arr // 256).astype(np.uint8))
            else:
                img = Image.fromarray(rgb_arr.astype(np.uint8))
        elif len(arr.shape) == 3:
            img = Image.fromarray(arr)
        else:
            arr_min, arr_max = arr.min(), arr.max()
            if arr_max > arr_min:
                arr_scaled = ((arr - arr_min) / (arr_max - arr_min) * 255.0).astype(np.uint8)
            else:
                arr_scaled = arr.astype(np.uint8)
            img = Image.fromarray(arr_scaled)
            
        # Create unique clean filename
        out_filename = f"ser_{series_num}_inst_{inst_num}.png"
        out_path = os.path.join(patient_img_dir, out_filename)
        img.save(out_path)
        return out_path, modality, series_num, inst_num
    except Exception as e:
        return None

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PARENT_DIR = os.path.dirname(_SCRIPT_DIR)
CLD_DXA_DIR = os.path.join(_PARENT_DIR, 'CLD DXA')

def process_patient_folder(folder):
    folder_path = os.path.join(CLD_DXA_DIR, folder)
    if not os.path.isdir(folder_path):
        return
        
    patient_name_tag = "Patient"
    patient_id_tag = "ID"
    
    # Extract anonymized patient ID from DICOM header
    anonymized_id = f"ANON_{folder}"
    for root, dirs, files in os.walk(folder_path):
        for f in files:
            if f.startswith('.') or f.upper() == 'DICOMDIR':
                continue
            try:
                ds = pydicom.dcmread(os.path.join(root, f), stop_before_pixels=True)
                anonymized_id = getattr(ds, 'PatientID', f"ANON_{folder}")
                break
            except Exception:
                pass
        if anonymized_id:
            break
            
    print(f"\nProcessing Folder {folder} (ID: {anonymized_id})...")
    
    # Establish directories
    patient_img_dir = os.path.join(_SCRIPT_DIR, "extracted_images", f"Patient_{folder}")
    patient_txt_dir = os.path.join(_SCRIPT_DIR, "extracted_text", f"Patient_{folder}")
    os.makedirs(patient_img_dir, exist_ok=True)
    os.makedirs(patient_txt_dir, exist_ok=True)
    
    dicom_files = []
    for root, dirs, files in os.walk(folder_path):
        for f in files:
            if f.startswith('.') or f.upper() == 'DICOMDIR':
                continue
            dicom_files.append(os.path.join(root, f))
            
    # Process images in parallel
    extracted_images = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(process_dicom_file, path, patient_img_dir) for path in dicom_files]
        for fut in futures:
            res = fut.result()
            if res:
                extracted_images.append(res)
                
    print(f"  Extracted {len(extracted_images)} images for Folder {folder}.")
    
    # Run OCR on the images
    ocr_count = 0
    for img_path, modality, ser, inst in extracted_images:
        base_name = os.path.basename(img_path).replace('.png', '')
        txt_output_path_base = os.path.join(patient_txt_dir, base_name)
        
        try:
            subprocess.run([
                TESSERACT_PATH,
                img_path,
                txt_output_path_base
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            ocr_count += 1
        except Exception as e:
            print(f"  OCR failed for {img_path}: {e}")
            
    print(f"  Completed OCR on {ocr_count} images for Folder {folder}.")

def main():
    folders = sorted([f for f in os.listdir(CLD_DXA_DIR) if os.path.isdir(os.path.join(CLD_DXA_DIR, f))], 
                     key=lambda x: int(x) if x.isdigit() else 999)
                     
    print(f"Found {len(folders)} patient folders to process: {folders}")
    
    for folder in folders:
        process_patient_folder(folder)
        
    print("\nAll patient images and text extracted successfully!")

if __name__ == "__main__":
    main()
