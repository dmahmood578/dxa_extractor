import os
import re

def extract_all_numeric_lines():
    text_base_dir = "dxa_extractor/extracted_text"
    folders = sorted([f for f in os.listdir(text_base_dir) if f.startswith('Patient_')], 
                     key=lambda x: int(x.split('_')[1]) if x.split('_')[1].isdigit() else 999)
                     
    print("EXTRACTING TABLE LINES FOR ALL PATIENTS:")
    print("=" * 80)
    
    for folder in folders:
        folder_path = os.path.join(text_base_dir, folder)
        txt_files = sorted([f for f in os.listdir(folder_path) if f.endswith('.txt')])
        
        print(f"\nPatient: {folder}")
        print("-" * 50)
        
        # We will collect unique matching lines across all files for this patient
        unique_matches = {}
        
        for f in txt_files:
            path = os.path.join(folder_path, f)
            lines = open(path, 'r').readlines()
            
            for line in lines:
                line_str = line.strip()
                l = line_str.lower()
                
                # Check for major regions
                is_region = any(reg in l for reg in ['neck', 'total', 'l1-l4', 'l1-l3', 'l2-l4'])
                # Must contain some numbers
                has_nums = any(c.isdigit() for c in l)
                
                if is_region and has_nums:
                    # Let's clean up whitespace a bit to check for uniqueness
                    key = re.sub(r'\s+', ' ', line_str)
                    if key not in unique_matches:
                        unique_matches[key] = f
                        
        for match_line, filename in sorted(unique_matches.items()):
            print(f"  [{filename}]: {match_line}")

extract_all_numeric_lines()
