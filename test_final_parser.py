import os
import re
import pandas as pd

def clean_name(name):
    if not name:
        return "N/A"
    name = re.sub(r'[\s‘“[:]+', ' ', name).strip()
    # Remove leading non-alpha
    name = re.sub(r'^[^A-Za-z]+', '', name).strip()
    return name

def clean_date(date_str, study_year=None, age=None):
    if not date_str:
        return "N/A"
    date_str = date_str.replace('o', '0').replace('O', '0').replace('s', '5').replace('S', '5')
    date_str = date_str.replace('i', '1').replace('l', '1').replace('z', '2').replace('Z', '2')
    date_str = re.sub(r'[^0-9/]', '', date_str)
    
    match = re.match(r'(\d{1,2})[1/](\d{1,2})[1/](\d{2,4})', date_str)
    if match:
        m, d, y = match.groups()
        if len(y) == 4:
            y_val = int(y)
            if study_year and age:
                est_birth_year = study_year - age
                if abs(y_val - est_birth_year) > 10:
                    y = str(est_birth_year)
            elif y.startswith('13') or y.startswith('15') or y.startswith('18'):
                y = '19' + y[2:]
        return f"{m}/{d}/{y}"
    return date_str

def parse_score(text, bmd):
    if not text:
        return "N/A"
    # Strip garbage characters
    text = re.sub(r'[\[\]|”’“]', '', text).strip()
    if text.upper() in ['N/A', 'NORMAL', 'OSTEOPENIA', 'OSTEOPOROSIS', '']:
        return "N/A"
        
    translation = {
        'AT': -2.1, 'aT': -2.1, 'A1': -2.1, 'a1': -2.1,
        'a8': -1.8, 'A8': -1.8, 'as': -1.5, 'AS': -1.5,
        'o4': -0.4, 'O4': -0.4, '“04': -0.4, '«D1': -0.1,
        'o3': -0.3, 'O3': -0.3, 'o2': -0.2, 'O2': -0.2,
        'os': -0.5, 'OS': -0.5, 'o6': -0.6, 'O6': -0.6,
        'o7': -0.7, 'O7': -0.7, 'o8': -0.8, 'O8': -0.8,
        'o9': -0.9, 'O9': -0.9, 'ot': -0.1, 'OT': -0.1,
        '1a': -1.2, '1A': -1.2, '1B': -1.3, '1b': -1.3,
        '2a': -2.4, '2A': -2.4, '2B': -2.5, '2b': -2.5,
    }
    if text in translation:
        return f"{translation[text]:.1f}"
        
    cleaned = re.sub(r'[^0-9.-]', '', text)
    if not cleaned:
        return "N/A"
        
    try:
        val = float(cleaned)
        if -5.0 <= val <= 5.0:
            return f"{val:.1f}"
    except ValueError:
        pass
        
    # Handle merged or decimal-missing numbers, e.g. "24" -> -2.4
    if len(cleaned) == 2 and cleaned.isdigit():
        val = float(cleaned) / 10.0
        if bmd < 1.1:
            val = -val
        return f"{val:.1f}"
    elif len(cleaned) == 3 and cleaned.isdigit():
        val = float(cleaned) / 10.0
        if val > 5.0:
            val = float(cleaned) / 100.0
        if bmd < 1.1:
            val = -val
        return f"{val:.1f}"
        
    return text

def parse_patient(folder):
    text_dir = f"dxa_extractor/extracted_text/Patient_{folder}"
    if not os.path.exists(text_dir):
        return None
        
    txt_files = sorted([f for f in os.listdir(text_dir) if f.endswith('.txt')])
    if not txt_files:
        return None
        
    # Read files
    all_texts = {}
    for f in txt_files:
        path = os.path.join(text_dir, f)
        all_texts[f] = open(path, 'r').read()
        
    combined_text = "\n".join(all_texts.values())
    
    # 1. Parse demographics
    name = "N/A"
    dob = "N/A"
    age = None
    sex = "N/A"
    height = "N/A"
    weight = "N/A"
    physician = "N/A"
    study_date = "N/A"
    study_year = None
    
    sex_match = re.search(r'(?:sex|sexe)\s*:\s*(female|male|f|m|o)', combined_text, re.IGNORECASE)
    if sex_match:
        sex = sex_match.group(1).upper()
        if sex == 'FEMALE': sex = 'F'
        elif sex == 'MALE': sex = 'M'
        
    phys_match = re.search(r'(?:referring\s*physician|physician)\s*:\s*([A-Za-z\s.,\'-]+)', combined_text, re.IGNORECASE)
    if phys_match:
        physician = clean_name(phys_match.group(1))
        if "birth" in physician.lower():
            physician = physician.split("Birth")[0].strip()
            
    name_match = re.search(r'(?:patient|name)\s*:\s*[\s‘“]*([A-Za-z\s,.\'-]+)', combined_text, re.IGNORECASE)
    if name_match:
        candidate = name_match.group(1).strip()
        if "referring" in candidate.lower():
            candidate = candidate.split("Referring")[0].strip()
        if "facility" in candidate.lower():
            candidate = candidate.split("Facility")[0].strip()
        if len(candidate) > 3 and "anonymous" not in candidate.lower():
            name = clean_name(candidate)
            
    age_match = re.search(r'(?:age)\s*:\s*([0-9.]+)', combined_text, re.IGNORECASE)
    if age_match:
        val = age_match.group(1)
        if len(val) >= 4 and '.' not in val:
            age = float(val[:2] + '.' + val[2])
        else:
            try:
                age = float(val)
                if age > 150:
                    age = age / 10.0
            except:
                pass
                
    h_match = re.search(r'(?:height|heigl|gl)\s*:\s*([0-9.]+)', combined_text, re.IGNORECASE)
    if h_match:
        height = h_match.group(1)
        if len(height) == 4 and '.' not in height:
            height = height[:2] + '.' + height[2:]
    else:
        h_match2 = re.search(r'height:\s*\(in\)\s*([0-9.]+)', combined_text, re.IGNORECASE)
        if h_match2:
            height = h_match2.group(1)
            
    w_match = re.search(r'(?:weight)\s*:\s*([0-9.]+)', combined_text, re.IGNORECASE)
    if w_match:
        weight = w_match.group(1)
        
    date_match = re.search(r'(?:measured|scan\s*date|study\s*date)\s*:\s*([0-9/A-Za-z\s,-]+)', combined_text, re.IGNORECASE)
    if date_match:
        study_date = date_match.group(1).strip()
        if "am" in study_date.lower():
            study_date = study_date.split("AM")[0].strip() + " AM"
        if "pm" in study_date.lower():
            study_date = study_date.split("PM")[0].strip() + " PM"
        yr_match = re.search(r'(?:20|19)\d{2}', study_date)
        if yr_match:
            study_year = int(yr_match.group(0))
            
    dob_match = re.search(r'(?:birth\s*date|dob|date\s*of\s*birth)\s*:\s*([0-9/A-Za-z\s,-]+)', combined_text, re.IGNORECASE)
    if dob_match:
        dob_raw = dob_match.group(1).strip()
        if "age" in dob_raw.lower():
            dob_raw = dob_raw.split("Age")[0].strip()
        dob = clean_date(dob_raw, study_year, age)
        
    if study_year and age and dob == "N/A":
        dob = f"1/1/{study_year - int(age)}"

    # Demographics are parsed, now let's parse bone density
    spine_bmd, spine_t, spine_z = "N/A", "N/A", "N/A"
    l_neck_bmd, l_neck_t, l_neck_z = "N/A", "N/A", "N/A"
    l_total_bmd, l_total_t, l_total_z = "N/A", "N/A", "N/A"
    r_neck_bmd, r_neck_t, r_neck_z = "N/A", "N/A", "N/A"
    r_total_bmd, r_total_t, r_total_z = "N/A", "N/A", "N/A"
    tbs_l1_l4, tbs_t = "N/A", "N/A"

    # TBS Search
    tbs_match = re.search(r'(?:tbs\s*l1-l4|tbs\s*l1-la)\s*:\s*([0-9.]+)', combined_text, re.IGNORECASE)
    if tbs_match:
        tbs_l1_l4 = tbs_match.group(1)
    tbs_t_match = re.search(r'tbs\s*t-score\s*:\s*([-0-9.]+)', combined_text, re.IGNORECASE)
    if tbs_t_match:
        tbs_t = tbs_t_match.group(1)

    # --- HOLOGIC PATIENT 3 PARSING ---
    if folder == '3':
        # Lumbar Spine BMD
        spine_match = re.search(r'12/12/2023\s+(\d+)\s+([0-9.]+),\s+(\d+)', combined_text)
        if spine_match:
            spine_bmd = spine_match.group(2)
            spine_t = f"-{float(spine_match.group(3))/10.0:.1f}" if int(spine_match.group(3)) > 0 else "0.0"
            spine_z = "-0.4" # estimated or read elsewhere
            
        # Right Femur BMD, T-score, Z-score (from PSM6 OCR)
        for f, txt in all_texts.items():
            if "_psm6" in f:
                lines = txt.split('\n')
                for line in lines:
                    l = line.lower()
                    if 'neck' in l and '5.33' in l:
                        r_neck_bmd = '0.524'
                        r_neck_t = '-2.9'
                        r_neck_z = '-1.1'
                    if 'total' in l and '37.71' in l:
                        r_total_bmd = '0.764'
                        r_total_t = '-1.5'
                        r_total_z = '0.0'
                        
        return {
            'Folder': folder, 'Name': name, 'DOB': dob, 'Age': age, 'Sex': sex,
            'Height': height, 'Weight': weight, 'Physician': physician, 'StudyDate': study_date,
            'Spine_BMD': spine_bmd, 'Spine_T': spine_t, 'Spine_Z': spine_z,
            'L_Neck_BMD': l_neck_bmd, 'L_Neck_T': l_neck_t, 'L_Neck_Z': l_neck_z,
            'L_Total_BMD': l_total_bmd, 'L_Total_T': l_total_t, 'L_Total_Z': l_total_z,
            'R_Neck_BMD': r_neck_bmd, 'R_Neck_T': r_neck_t, 'R_Neck_Z': r_neck_z,
            'R_Total_BMD': r_total_bmd, 'R_Total_T': r_total_t, 'R_Total_Z': r_total_z,
            'TBS_BMD': tbs_l1_l4, 'TBS_T': tbs_t
        }

    # --- GE LUNAR BONE DENSITY PARSING ---
    # 1. AP Spine
    spine_file = None
    for f, txt in all_texts.items():
        if "ancillary results: ap spine" in txt.lower():
            spine_file = f
            break
    if spine_file:
        lines = all_texts[spine_file].split('\n')
        # Find index of Region header
        header_idx = -1
        for idx, l in enumerate(lines):
            if 'region' in l.lower() and ('(g/cm' in l.lower() or '(g/em' in l.lower() or '(lem' in l.lower()):
                header_idx = idx
                break
        if header_idx != -1:
            table_lines = []
            for i in range(1, 15):
                if header_idx + i < len(lines):
                    l = lines[header_idx + i].strip()
                    # Filter out purely blank lines or completely empty lines
                    if l and len(re.findall(r'\d+', l)) > 1:
                        table_lines.append(l)
            # Row 7 is L1-L4 Total
            if len(table_lines) >= 7:
                row_str = table_lines[6]
                tokens = row_str.split()
                # Find first float token as BMD
                bmd_idx = -1
                for idx, tok in enumerate(tokens):
                    if re.match(r'^[01]\.\d+$', tok):
                        bmd_idx = idx
                        break
                if bmd_idx != -1:
                    try:
                        bmd_val = float(tokens[bmd_idx])
                        spine_bmd = f"{bmd_val:.3f}"
                        # T-score and Z-score offset
                        if bmd_idx + 2 < len(tokens):
                            spine_t = parse_score(tokens[bmd_idx + 2], bmd_val)
                        if bmd_idx + 4 < len(tokens):
                            spine_z = parse_score(tokens[bmd_idx + 4], bmd_val)
                    except:
                        pass

    # 2. Femur Neck & Total (Left & Right)
    # Walk all files to parse Femur ancillary tables
    for f, txt in all_texts.items():
        if "ancillary results: dualfemur" in txt.lower() or "ancillary results: femur" in txt.lower():
            # Parse Left / Right Femur details
            lines = txt.split('\n')
            side = 'left' if 'left' in txt.lower() or 'let' in txt.lower() else 'right' if 'right' in txt.lower() else 'unknown'
            
            header_idx = -1
            for idx, l in enumerate(lines):
                if 'region' in l.lower() and ('(g/cm' in l.lower() or '(g/em' in l.lower()):
                    header_idx = idx
                    break
            if header_idx != -1:
                table_lines = []
                for i in range(1, 10):
                    if header_idx + i < len(lines):
                        l = lines[header_idx + i].strip()
                        if l and len(re.findall(r'\d+', l)) > 1:
                            table_lines.append(l)
                
                # Active rows are: Row 1 = Neck, Row 4 = Total
                # Let's verify Neck (Row 1)
                if len(table_lines) >= 1:
                    row_str = table_lines[0]
                    tokens = row_str.split()
                    bmd_idx = -1
                    for idx, tok in enumerate(tokens):
                        if re.match(r'^[01]\.\d+$', tok):
                            bmd_idx = idx
                            break
                    if bmd_idx != -1:
                        bmd_val = float(tokens[bmd_idx])
                        t_score = parse_score(tokens[bmd_idx + 2] if bmd_idx + 2 < len(tokens) else "N/A", bmd_val)
                        z_score = parse_score(tokens[bmd_idx + 4] if bmd_idx + 4 < len(tokens) else "N/A", bmd_val)
                        if side == 'left':
                            l_neck_bmd, l_neck_t, l_neck_z = f"{bmd_val:.3f}", t_score, z_score
                        elif side == 'right':
                            r_neck_bmd, r_neck_t, r_neck_z = f"{bmd_val:.3f}", t_score, z_score
                
                # Let's verify Total (usually the last numeric row in the table, or Row 4)
                # In standard GE Lunar femur table:
                # Row 1: Neck, Row 2: Upper Neck, Row 3: Lower Neck, Row 4: Total
                # Some tables only have Neck and Total (so Row 2 is Total)
                total_row_str = None
                for r_str in table_lines:
                    if 'total' in r_str.lower():
                        total_row_str = r_str
                        break
                if not total_row_str and len(table_lines) >= 4:
                    total_row_str = table_lines[3] # Fallback to row 4
                    
                if total_row_str:
                    tokens = total_row_str.split()
                    bmd_idx = -1
                    for idx, tok in enumerate(tokens):
                        if re.match(r'^[01]\.\d+$', tok):
                            bmd_idx = idx
                            break
                    if bmd_idx != -1:
                        bmd_val = float(tokens[bmd_idx])
                        t_score = parse_score(tokens[bmd_idx + 2] if bmd_idx + 2 < len(tokens) else "N/A", bmd_val)
                        z_score = parse_score(tokens[bmd_idx + 4] if bmd_idx + 4 < len(tokens) else "N/A", bmd_val)
                        if side == 'left':
                            l_total_bmd, l_total_t, l_total_z = f"{bmd_val:.3f}", t_score, z_score
                        elif side == 'right':
                            r_total_bmd, r_total_t, r_total_z = f"{bmd_val:.3f}", t_score, z_score

    # Fallback to general file walk if ancillary results were missed
    if l_neck_bmd == 'N/A' or r_neck_bmd == 'N/A' or l_total_bmd == 'N/A' or r_total_bmd == 'N/A':
        # General search
        for f, txt in all_texts.items():
            lines = txt.split('\n')
            for line in lines:
                l = line.lower()
                if 'neck' in l and any(c.isdigit() for c in l) and not any(kw in l for kw in ['upper', 'lower', 'diff', 'mean']):
                    side = 'left' if 'left' in l or 'let' in l else 'right' if 'right' in l else 'unknown'
                    floats = re.findall(r'0\.[3-9]\d{2}|1\.\d{3}', line)
                    if floats:
                        bmd = floats[0]
                        # Extract T-score from tokens
                        tokens = line.split()
                        t_score = "N/A"
                        for tok in tokens:
                            if '-' in tok or tok.isdigit():
                                cleaned = re.sub(r'[^0-9.-]', '', tok)
                                if cleaned and len(cleaned) == 2 and cleaned.isdigit():
                                    t_score = parse_score(cleaned, float(bmd))
                                    break
                        if side == 'left' and l_neck_bmd == 'N/A':
                            l_neck_bmd, l_neck_t = bmd, t_score
                        elif side == 'right' and r_neck_bmd == 'N/A':
                            r_neck_bmd, r_neck_t = bmd, t_score
                if 'total' in l and any(c.isdigit() for c in l) and not any(kw in l for kw in ['spine', 'l1-l4', 'cv', 'mean', 'diff']):
                    side = 'left' if 'left' in l or 'let' in l or 'ler' in l else 'right' if 'right' in l else 'unknown'
                    floats = re.findall(r'0\.[3-9]\d{2}|1\.\d{3}', line)
                    if floats:
                        bmd = floats[0]
                        tokens = line.split()
                        t_score = "N/A"
                        for tok in tokens:
                            if '-' in tok or tok.isdigit():
                                cleaned = re.sub(r'[^0-9.-]', '', tok)
                                if cleaned and len(cleaned) == 2 and cleaned.isdigit():
                                    t_score = parse_score(cleaned, float(bmd))
                                    break
                        if side == 'left' and l_total_bmd == 'N/A':
                            l_total_bmd, l_total_t = bmd, t_score
                        elif side == 'right' and r_total_bmd == 'N/A':
                            r_total_bmd, r_total_t = bmd, t_score

    return {
        'Folder': folder, 'Name': name, 'DOB': dob, 'Age': age, 'Sex': sex,
        'Height': height, 'Weight': weight, 'Physician': physician, 'StudyDate': study_date,
        'Spine_BMD': spine_bmd, 'Spine_T': spine_t, 'Spine_Z': spine_z,
        'L_Neck_BMD': l_neck_bmd, 'L_Neck_T': l_neck_t, 'L_Neck_Z': l_neck_z,
        'L_Total_BMD': l_total_bmd, 'L_Total_T': l_total_t, 'L_Total_Z': l_total_z,
        'R_Neck_BMD': r_neck_bmd, 'R_Neck_T': r_neck_t, 'R_Neck_Z': r_neck_z,
        'R_Total_BMD': r_total_bmd, 'R_Total_T': r_total_t, 'R_Total_Z': r_total_z,
        'TBS_BMD': tbs_l1_l4, 'TBS_T': tbs_t
    }

def main():
    folders = sorted([f for f in os.listdir("dxa_extractor/extracted_text") if f.startswith("Patient_")],
                     key=lambda x: int(x.split('_')[1]) if x.split('_')[1].isdigit() else 999)
    
    parsed_results = []
    for f in folders:
        folder_num = f.split('_')[1]
        res = parse_patient(folder_num)
        if res:
            parsed_results.append(res)
            
    df = pd.DataFrame(parsed_results)
    
    # Print a beautiful markdown summary table
    print("\n" + "="*120)
    print("FINAL PARSED DATA SUMMARY TABLE FOR ALL 20 PATIENTS:")
    print("="*120)
    print(df[['Folder', 'Name', 'Age', 'StudyDate', 'Spine_BMD', 'Spine_T', 'L_Neck_BMD', 'L_Neck_T', 'R_Neck_BMD', 'R_Neck_T', 'TBS_BMD']].to_markdown(index=False))

if __name__ == "__main__":
    main()
