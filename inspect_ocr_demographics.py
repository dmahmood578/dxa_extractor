import os
import re

def inspect_demographics():
    text_base_dir = "dxa_extractor/extracted_text"
    folders = sorted([f for f in os.listdir(text_base_dir) if f.startswith('Patient_')], 
                     key=lambda x: int(x.split('_')[1]) if x.split('_')[1].isdigit() else 999)
                     
    for folder in folders:
        folder_path = os.path.join(text_base_dir, folder)
        txt_files = [f for f in os.listdir(folder_path) if f.endswith('.txt')]
        if not txt_files:
            continue
            
        # We just need to read the first non-empty text file to get demographics, 
        # since all pages for a patient share the same header.
        demographics_lines = []
        found = False
        for f in sorted(txt_files):
            if found:
                break
            path = os.path.join(folder_path, f)
            lines = open(path, 'r').readlines()
            for line in lines:
                l = line.strip()
                # Look for lines containing "Patient:" or "Birth Date:" or "Referring Physician"
                if "patient:" in l.lower() or "birth date:" in l.lower() or "physician:" in l.lower() or "height:" in l.lower():
                    demographics_lines.append((f, l))
                    if len(demographics_lines) >= 3:
                        found = True
                        break
                        
        print(f"\n--- Patient Folder: {folder} ---")
        for f, l in demographics_lines:
            print(f"  [{f}]: {l}")

inspect_demographics()
