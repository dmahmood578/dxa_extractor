import os
import re

def debug_spine():
    text_base_dir = "dxa_extractor/extracted_text"
    folders = sorted([f for f in os.listdir(text_base_dir) if f.startswith('Patient_')], 
                     key=lambda x: int(x.split('_')[1]) if x.split('_')[1].isdigit() else 999)
                     
    for folder in folders:
        # Skip Hologic Patient 3 for now, as we're analyzing GE Lunar
        if folder == 'Patient_3':
            continue
            
        folder_path = os.path.join(text_base_dir, folder)
        txt_files = sorted([f for f in os.listdir(folder_path) if f.endswith('.txt')])
        
        # Find the ancillary spine report file
        spine_file = None
        for f in txt_files:
            path = os.path.join(folder_path, f)
            content = open(path, 'r').read()
            if "ancillary results: ap spine" in content.lower():
                spine_file = path
                break
                
        if not spine_file:
            print(f"Patient {folder}: No ancillary spine file found")
            continue
            
        # Parse the 10 rows in the table
        lines = open(spine_file, 'r').read().split('\n')
        table_lines = []
        for line in lines:
            l = line.strip()
            # If it's a line with numbers after the "Region" header
            if l and any(c.isdigit() for c in l) and not any(kw in l.lower() for kw in ['ancillary', 'results', 'bmd', 't-score', 'z-score', 'height', 'weight', 'measured', 'analyzed', 'patient', 'birth', 'phone', 'marlton', 'medicine', 'hospital', 'civic', 'philadelphia', 'ch']) and len(l) > 10:
                table_lines.append(l)
                
        print(f"\n--- {folder} ({os.path.basename(spine_file)}) ---")
        print(f"Total table rows found: {len(table_lines)}")
        for idx, row in enumerate(table_lines):
            # Print row index and content
            # Row 7 is index 6 (L1-L4)
            label = f"Row {idx+1}"
            if idx == 6:
                label += " (L1-L4 Total)"
            print(f"  {label:18s}: {row}")

debug_spine()
