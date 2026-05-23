import os

def inspect_tables():
    text_base_dir = "dxa_extractor/extracted_text"
    for p_folder in ["Patient_1", "Patient_2", "Patient_3", "Patient_4"]:
        folder_path = os.path.join(text_base_dir, p_folder)
        if not os.path.exists(folder_path):
            continue
            
        print(f"\n==================== {p_folder} ====================")
        txt_files = sorted([f for f in os.listdir(folder_path) if f.endswith('.txt')])
        
        # Check files containing tables
        for f in txt_files:
            path = os.path.join(folder_path, f)
            content = open(path, 'r').read()
            lines = content.split('\n')
            
            # Print if there is a table region match
            is_table = False
            matched_lines = []
            for idx, line in enumerate(lines):
                l = line.lower()
                if any(region in l for region in ['neck', 'total', 'l1', 'l2', 'l3', 'l4', 'l1-l4']):
                    # Check if there are numbers in this line
                    if any(char.isdigit() for char in l):
                        matched_lines.append((idx + 1, line.strip()))
                        is_table = True
                        
            if is_table:
                print(f"\n  File: {f} (has {len(matched_lines)} numeric table lines)")
                # Print first 15 matched lines
                for lno, l in matched_lines[:15]:
                    print(f"    Line {lno:02d}: {l}")

inspect_tables()
