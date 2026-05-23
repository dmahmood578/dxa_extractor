import os
import pydicom
from PIL import Image
import numpy as np

def extract_dicom_images(directory, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    print(f"Scanning for DICOM image files in {directory}...")
    
    extracted_count = 0
    for root, dirs, files in os.walk(directory):
        for f in files:
            if f.startswith('.'):
                continue
            path = os.path.join(root, f)
            try:
                ds = pydicom.dcmread(path)
                if hasattr(ds, 'PixelData'):
                    # Get patient and series info
                    patient_id = getattr(ds, 'PatientID', 'UNKNOWN')
                    modality = getattr(ds, 'Modality', 'UNKNOWN')
                    series_num = getattr(ds, 'SeriesNumber', 'UNKNOWN')
                    inst_num = getattr(ds, 'InstanceNumber', 'UNKNOWN')
                    
                    # Read pixel array
                    arr = ds.pixel_array
                    
                    # Convert to RGB if needed or handle palette color
                    photo_interp = getattr(ds, 'PhotometricInterpretation', 'MONOCHROME2')
                    
                    if photo_interp == 'PALETTE COLOR':
                        # Convert using pydicom's apply_color_lut
                        from pydicom.pixel_data_handlers.util import apply_color_lut
                        rgb_arr = apply_color_lut(arr, ds)
                        if rgb_arr.dtype == np.uint16:
                            img = Image.fromarray((rgb_arr // 256).astype(np.uint8))
                        else:
                            img = Image.fromarray(rgb_arr.astype(np.uint8))
                    elif len(arr.shape) == 3:
                        # Already RGB or multi-channel
                        img = Image.fromarray(arr)
                    else:
                        # Grayscale
                        # Rescale if needed
                        arr_min, arr_max = arr.min(), arr.max()
                        if arr_max > arr_min:
                            arr_scaled = ((arr - arr_min) / (arr_max - arr_min) * 255.0).astype(np.uint8)
                        else:
                            arr_scaled = arr.astype(np.uint8)
                        img = Image.fromarray(arr_scaled)
                        
                    # Save image
                    out_filename = f"pat_{patient_id}_mod_{modality}_ser_{series_num}_inst_{inst_num}.png"
                    out_path = os.path.join(output_dir, out_filename)
                    img.save(out_path)
                    print(f"Saved: {out_path} ({photo_interp}, {arr.shape})")
                    extracted_count += 1
            except Exception as e:
                # print(f"Error processing {path}: {e}")
                pass
                
    print(f"Extracted {extracted_count} images.")

# Let's extract images for patient folder 1
extract_dicom_images("CLD DXA/1", "dxa_extractor/extracted_images/1")
