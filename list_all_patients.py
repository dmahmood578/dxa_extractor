import os
import pydicom
import pandas as pd

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PARENT_DIR = os.path.dirname(_SCRIPT_DIR)
CLD_DXA_DIR = os.path.join(_PARENT_DIR, 'CLD DXA')

def scan_patient_demographics():
    patient_data = []
    
    for folder in sorted(os.listdir(CLD_DXA_DIR), key=lambda x: int(x) if x.isdigit() else 999):
        folder_path = os.path.join(CLD_DXA_DIR, folder)
        if not os.path.isdir(folder_path):
            continue
            
        # Find first actual DICOM file (skipping DICOMDIR) to get patient demographics
        found = False
        for root, dirs, files in os.walk(folder_path):
            if found:
                break
            for f in sorted(files):
                if f.startswith('.') or f.upper() == 'DICOMDIR':
                    continue
                path = os.path.join(root, f)
                try:
                    ds = pydicom.dcmread(path, stop_before_pixels=True)
                    # We found a valid DICOM file
                    pat_name = str(getattr(ds, 'PatientName', 'N/A'))
                    pat_id = str(getattr(ds, 'PatientID', 'N/A'))
                    pat_sex = str(getattr(ds, 'PatientSex', 'N/A'))
                    pat_dob = str(getattr(ds, 'PatientBirthDate', 'N/A'))
                    acc_num = str(getattr(ds, 'AccessionNumber', 'N/A'))
                    study_date = str(getattr(ds, 'StudyDate', 'N/A'))
                    study_time = str(getattr(ds, 'StudyTime', 'N/A'))
                    manufacturer = str(getattr(ds, 'Manufacturer', 'N/A'))
                    model = str(getattr(ds, 'ManufacturerModelName', 'N/A'))
                    
                    patient_data.append({
                        'Folder': folder,
                        'PatientID': pat_id,
                        'PatientName': pat_name,
                        'Sex': pat_sex,
                        'DOB': pat_dob,
                        'AccessionNumber': acc_num,
                        'StudyDate': study_date,
                        'StudyTime': study_time,
                        'Manufacturer': manufacturer,
                        'Model': model
                    })
                    found = True
                    break
                except Exception:
                    pass
                    
    df = pd.DataFrame(patient_data)
    print(f"Demographics for {len(df)} patient folders:")
    print(df.to_string(index=False))
    
    # Save this to CSV
    data_dir = os.path.join(_SCRIPT_DIR, 'data')
    os.makedirs(data_dir, exist_ok=True)
    csv_path = os.path.join(data_dir, 'patient_cohort_demographics.csv')
    df.to_csv(csv_path, index=False)
    print(f"\nSaved cohort demographics to {csv_path}")

scan_patient_demographics()
