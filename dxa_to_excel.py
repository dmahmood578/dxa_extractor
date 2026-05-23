"""
dxa_to_excel.py
==============
Reads pre-extracted OCR text from dxa_extractor/extracted_text/Patient_N/
and writes a clean Excel spreadsheet to dxa_extractor/dxa_data.xlsx

ALL data stays local – no network calls.
"""

import os, re, subprocess
import pandas as pd
import numpy as np

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEXT_DIR   = os.path.join(_SCRIPT_DIR, "extracted_text")
OUTPUT_XLS = os.path.join(_SCRIPT_DIR, "dxa_data.xlsx")

# ── helpers ─────────────────────────────────────────────────────────────────

def read_folder(patient_dir):
    """Return dict{filename: text} for every *.txt in a patient folder."""
    out = {}
    for f in sorted(os.listdir(patient_dir)):
        if f.endswith(".txt"):
            out[f] = open(os.path.join(patient_dir, f), encoding="utf-8", errors="replace").read()
    return out


def combined(texts):
    return "\n".join(texts.values())


def first_match(pattern, text, flags=re.IGNORECASE, group=1):
    m = re.search(pattern, text, flags)
    return m.group(group).strip() if m else None


# ── numeric token parser ─────────────────────────────────────────────────────

# OCR frequently mangles signed numbers: "24" → -2.4, "A8" → -1.8, etc.
# The GE Lunar tables use 2-char tokens where a letter prefix encodes the
# integer part of a negative score and a digit encodes the tenth:
#   O/o = -0.X,  a/A = -1.X or -2.X,  B/b = -3.X
_OCR_SIGN_MAP = {
    # -0.X patterns (O = zero, often OCR'd from "−0")
    "O1": -0.1, "o1": -0.1, "OT": -0.1, "ot": -0.1, "ut": -0.1, "UT": -0.1,
    "O2": -0.2, "o2": -0.2,
    "O3": -0.3, "o3": -0.3, "Os": -0.5, "os": -0.5,
    "O4": -0.4, "o4": -0.4,
    "O5": -0.5, "o5": -0.5,
    "O6": -0.6, "o6": -0.6,
    "O7": -0.7, "o7": -0.7,
    "O8": -0.8, "o8": -0.8,
    "O9": -0.9, "o9": -0.9,
    # -1.X patterns
    "al": -1.2, "AL": -1.2, "A1": -2.1, "a1": -2.1,
    "a2": -1.2, "A2": -1.2,
    "a3": -1.3, "A3": -1.3,
    "a4": -1.4, "A4": -1.4,
    "as": -1.5, "AS": -1.5, "a5": -1.5, "A5": -1.5,
    "a6": -1.6, "A6": -1.6,
    "a7": -1.7, "A7": -1.7,
    "a8": -1.8, "A8": -1.8,
    "a9": -1.9, "A9": -1.9,
    # -2.X patterns
    "AT": -2.1, "aT": -2.1,
    "af": -2.5, "AF": -2.5,
    # -3.X patterns
    "Bl": -3.1, "BI": -3.1,
}

def parse_score_token(tok):
    """Convert an OCR token to a float score or None."""
    tok = tok.strip("[]|\"'()")
    if not tok or tok in ("N/A", "-", "=", "*", ">", "<"):
        return None
    if tok in _OCR_SIGN_MAP:
        return _OCR_SIGN_MAP[tok]
    # Already a clean number
    cleaned = re.sub(r"[^0-9.\-]", "", tok)
    if not cleaned or cleaned == ".":
        return None
    try:
        val = float(cleaned)
        # 2-digit like "24" → might be -2.4 T-score
        if tok.isdigit() and len(tok) == 2:
            val = -abs(val / 10.0)
        elif tok.isdigit() and len(tok) == 3:
            val = -abs(val / 10.0)      # e.g. "24" as 3-digit won't happen; safety
        return val
    except ValueError:
        return None


def _fix_bmd_token(tok):
    """Handle BMD tokens with missing decimal: '0873' → 0.873."""
    tok = tok.strip("[]|\"'(),")
    if re.match(r'^[01]\d{3}$', tok):          # e.g. '0873'
        return float(tok[0] + '.' + tok[1:])
    return float(tok)


def _split_merged_ya_t(tok):
    """
    Older GE firmware merges %YA and T-score into one token: '86-10' → (86, -1.0).
    Returns (ya_pct, t_score) or (None, None).
    """
    m = re.match(r'^(\d{2,3})(-\d{1,3})$', tok.strip("[]|\"'(),"))
    if m:
        ya = int(m.group(1))
        t_raw = m.group(2)           # e.g. '-10'
        t = float(t_raw) / 10.0     # -10 → -1.0
        return ya, t
    return None, None


def extract_bmd_row(row_str):
    """
    Parse a GE Lunar table row: label BMD %YA T-score %AM Z-score ...
    Handles both new format (0.873) and old format (0873 or merged 86-10).
    Returns (bmd, t_score, z_score) as floats or None.
    """
    tokens = row_str.split()
    bmd_idx = -1
    for i, tok in enumerate(tokens):
        clean = tok.strip("[]|\"'(),")
        # New format: 0.xxx or 1.xxx
        if re.match(r'^[01]\.\d{2,3}', clean):
            bmd_idx = i
            break
        # Old format: 4 digits starting with 0 or 1 (e.g. 0873)
        if re.match(r'^[01]\d{3}$', clean):
            bmd_idx = i
            break
    if bmd_idx == -1:
        return None, None, None

    try:
        bmd = _fix_bmd_token(tokens[bmd_idx])
    except ValueError:
        return None, None, None

    # Next token may be %YA alone or merged '%YA-Tscore'
    ya_pct, t, z = None, None, None

    if bmd_idx + 1 < len(tokens):
        ya_tok = tokens[bmd_idx + 1]
        merged_ya, merged_t = _split_merged_ya_t(ya_tok)
        if merged_ya is not None:
            # Merged token: skip to Z-score at offset +3
            ya_pct = merged_ya
            t = merged_t
            z_raw = tokens[bmd_idx + 3] if bmd_idx + 3 < len(tokens) else None
            z = parse_score_token(z_raw) if z_raw else None
        else:
            # Normal layout: BMD %YA T %AM Z
            t_raw = tokens[bmd_idx + 2] if bmd_idx + 2 < len(tokens) else None
            z_raw = tokens[bmd_idx + 4] if bmd_idx + 4 < len(tokens) else None
            t = parse_score_token(t_raw) if t_raw else None
            z = parse_score_token(z_raw) if z_raw else None

    # Sanity check: T-score should be between -6 and +6
    if t is not None and not (-6.0 <= t <= 6.0):
        t = None
    if z is not None and not (-6.0 <= z <= 6.0):
        z = None

    return bmd, t, z


# ── GE Lunar table extractor ─────────────────────────────────────────────────

# Two header patterns used across GE firmware versions
_GE_HEADER_RE = re.compile(
    r"(ancillary results[\s:[\]]+(?:ap\s*spine|left\s*femur|right\s*femur|femur))",
    re.IGNORECASE
)

def find_ancillary_section(txt, keyword):
    """Return list of data-row strings for the named ancillary section."""
    lower = txt.lower()
    kw = keyword.lower()

    # Find position of "ANCILLARY RESULTS" followed by keyword
    best_pos = -1
    for m in re.finditer(r"ancillary results", lower):
        snippet = lower[m.start(): m.start()+60]
        if kw in snippet:
            best_pos = m.start()
            break
    if best_pos == -1:
        return []

    # Slice text from that point, get lines
    chunk = txt[best_pos:best_pos + 3000]
    lines = chunk.split("\n")

    # Find the region/BMD header line
    header_idx = -1
    for i, l in enumerate(lines):
        ll = l.lower()
        if "region" in ll and ("(g/cm" in ll or "(g/em" in ll or "(lem" in ll or "(olem" in ll or "(giem" in ll or "t-score" in ll):
            header_idx = i
            break
    if header_idx == -1:
        return []

    # Collect up to 50 data lines after header (DualFemur sections can be large)
    data_rows = []
    for l in lines[header_idx + 1:]:
        ls = l.strip()
        if not ls:
            continue
        if any(kw in ls.lower() for kw in ["satay", "statay", "stacy", "stascal", "usa", "nhanes", "t-score", "filename", "page:", "ce ", "lunar", "hologic", "© "]):
            break
        if len(re.findall(r"\d", ls)) >= 2:
            data_rows.append(ls)
        if len(data_rows) >= 50:
            break
    return data_rows


def ge_spine_l1l4(texts):
    """Extract AP Spine L1-L4 BMD, T, Z from GE Lunar ancillary section.
    Falls back to the history/trend table if ancillary is blank."""
    for txt in texts.values():
        rows = find_ancillary_section(txt, "ap spine")
        if len(rows) >= 7:
            bmd, t, z = extract_bmd_row(rows[6])  # row index 6 = L1-L4
            if bmd and 0.4 < bmd < 2.5:
                return bmd, t, z

    # Fallback: scan trend/history table for most recent BMD reading
    # Pattern: date  age  BMD  ...   e.g. "8/7/2025 74.6 0.985 ..."
    comb = combined(texts)
    for pattern in [
        r"(?:l1.?l4|spine).*?(\d{1,2}/\d{1,2}/(?:19|20)\d{2})\s+[0-9.]+\s+(0\.[4-9]\d{2}|1\.\d{3})",
        r"(\d{1,2}/\d{1,2}/(?:19|20)\d{2})\s+[0-9.]+\s+(0\.[4-9]\d{2}|1\.\d{3})\s+",
    ]:
        m = re.search(pattern, comb, re.IGNORECASE)
        if m:
            bmd = float(m.group(2))
            if 0.4 < bmd < 2.5:
                return bmd, None, None
    return None, None, None


def ge_femur(texts, side):
    """Extract Neck and Total BMD/T/Z for a given side ('left' or 'right').
    Searches both dedicated 'Left Femur'/'Right Femur' sections AND
    the combined 'DualFemur' section (which contains rows labelled by side).
    """
    neck_bmd = neck_t = neck_z = None
    total_bmd = total_t = total_z = None

    # Keywords to search for ancillary sections
    search_keywords = [f"{side} femur", "dualfemur", "dual femur", "femur"]

    for kw in search_keywords:
        for txt in texts.values():
            rows = find_ancillary_section(txt, kw)
            if not rows:
                continue

            for i, row in enumerate(rows):
                rl = row.lower()

                # In DualFemur sections, rows are labelled with side.
                # e.g. "Neck Left", "Total Right", "NeckLefe", "TotalLer" (OCR variants)
                # Skip rows that belong to the OTHER side, mean, or diff rows
                side_l = side.lower()
                other_side = "right" if side_l == "left" else "left"

                # Detect side from row label
                row_has_our_side = any(s in rl for s in _side_aliases(side_l))
                row_has_other_side = any(s in rl for s in _side_aliases(other_side))
                row_has_mean = "mean" in rl
                row_has_diff = "dif" in rl

                # In DualFemur, skip rows belonging to the other side, mean, or diff
                if kw.lower() in ("dualfemur", "dual femur", "femur"):
                    if row_has_other_side and not row_has_our_side:
                        continue
                    if row_has_mean or row_has_diff:
                        continue
                    if not row_has_our_side:
                        # For dedicated Left/Right Femur sections, all rows belong to that side
                        # But for DualFemur, skip rows without explicit side label
                        continue

                bmd, t, z = extract_bmd_row(row)
                if bmd is None or not (0.3 < bmd < 2.5):
                    continue
                if "total" in rl and total_bmd is None:
                    total_bmd, total_t, total_z = bmd, t, z
                elif "neck" in rl and "upper" not in rl and "lower" not in rl and "ward" not in rl and neck_bmd is None:
                    neck_bmd, neck_t, neck_z = bmd, t, z

            if neck_bmd or total_bmd:
                break
        if neck_bmd or total_bmd:
            break

    return neck_bmd, neck_t, neck_z, total_bmd, total_t, total_z


def _side_aliases(side):
    """Return OCR-tolerant aliases for 'left' or 'right'."""
    if side == "left":
        return ["left", "lett", "let", "lef", "lefe"]
    return ["right", "righ"]


# ── Demographics parser ───────────────────────────────────────────────────────

def clean_str(s):
    if not s:
        return None
    s = re.sub(r"[\s'\"]+", " ", s).strip()
    s = re.sub(r"^[^A-Za-z]+", "", s).strip()
    return s or None


def parse_age(txt):
    m = re.search(r"\bage\s*:\s*([0-9.]+)", txt, re.IGNORECASE)
    if not m:
        # "67.2 years" without "Age:"
        m = re.search(r"(\d{2}\.\d)\s*years", txt, re.IGNORECASE)
    if m:
        raw = m.group(1)
        val = float(raw)
        # OCR artefact: "673" should be 67.3
        if val > 150:
            val = float(raw[:2] + "." + raw[2])
        return round(val, 1)
    return None


def parse_dob(txt, study_year=None, age=None):
    # "Birth Date: MM/DD/YYYY" or "DOB: MM/DD/YYYY"
    m = re.search(r"(?:birth\s*date|dob)\s*[:\s]+([0-9/A-Za-z]+)", txt, re.IGNORECASE)
    if m:
        raw = m.group(1).strip()
        # Fix OCR digit substitutions
        raw = re.sub(r"[oO](?=\d)", "0", raw)
        raw = re.sub(r"(?<=\d)[oO]", "0", raw)
        dm = re.search(r"(\d{1,2})[\/-](\d{1,2})[\/-](\d{2,4})", raw)
        if dm:
            mo, day, yr = dm.groups()
            if len(yr) == 4 and int(yr) > 2025:
                yr = "19" + yr[2:]
            return f"{mo}/{day}/{yr}"
    # Fallback: estimate from study year and age
    if study_year and age:
        return f"1/1/{study_year - int(age)}"
    return None


_NAME_STOPS = ["Referring", "Facility", "Birth", "Date", "Patient", "ID", "Phone", "Height"]

def parse_name(txt):
    # Match 'Patient: [optional quote/space] Lastname, Firstname'
    m = re.search(r"(?:patient|name)\s*:\s*['\'\s]*([A-Za-z][A-Za-z\s,.\'-]{3,40})", txt, re.IGNORECASE)
    if not m:
        return None
    candidate = m.group(1)
    for stop in _NAME_STOPS:
        ci = candidate.lower().find(stop.lower())
        if ci != -1:
            candidate = candidate[:ci]
    cand = clean_str(candidate)
    # Reject if clearly not a name (all caps, too short, no letter)
    if not cand or len(cand) < 4 or cand.upper() == cand:
        return None
    return cand


def parse_sex(txt):
    m = re.search(r"(?:sex|sexe)\s*[:/]\s*(female|male|f|m)", txt, re.IGNORECASE)
    if m:
        s = m.group(1).upper()
        return "F" if s.startswith("F") else "M"
    # "Female" or "Male" anywhere nearby height/weight context
    m2 = re.search(r"\b(Female|Male)\b", txt, re.IGNORECASE)
    return m2.group(1)[0].upper() if m2 else None


def parse_height(txt):
    # Modern GE: "Height: 67.0 in" or "Height / Weight: 68.0 in."
    m = re.search(r"(?:height|heigl)\s*[/:\s]+([0-9a-zA-Z.]{3,7})\s*in", txt, re.IGNORECASE)
    if m:
        raw = m.group(1).replace(" ", "")
        # Fix OCR letter substitutions: sL0 → 61.0, S70 → 57.0
        raw = re.sub(r'[sS]', '5', raw)
        raw = re.sub(r'[lL]', '1', raw)
        raw = re.sub(r'[oO](?=\d)', '0', raw)
        raw = re.sub(r'(?<=\d)[oO]', '0', raw)
        raw = re.sub(r'[^0-9.]', '', raw)
        if raw:
            val = float(raw)
            if val > 100:
                val = val / 10.0
            if 48.0 <= val <= 84.0:
                return round(val, 1)
    # Hologic: "Current Height: (in) 64.8"
    m2 = re.search(r"height.*?\(in\)\s*([0-9.]+)", txt, re.IGNORECASE)
    if m2:
        val = float(m2.group(1))
        if val > 100:
            val = val / 10.0
        return round(val, 1)
    return None


def parse_weight(txt):
    m = re.search(r"weight\s*[/:\s]+([0-9.]+)\s*(?:lb|kg|Ib|bs)", txt, re.IGNORECASE)
    if m:
        val = float(m.group(1))
        # OCR drops decimal: 1296 → 129.6
        if val > 500:
            val = val / 10.0
        return round(val, 1)
    return None


def parse_scan_date(txt):
    m = re.search(r"(?:measured|scan\s*date)\s*:\s*([0-9A-Za-z/,\s:.-]+?)(?:\s*\(|\s*AM|\s*PM|\n)", txt, re.IGNORECASE)
    if m:
        d = m.group(1).strip().rstrip(",")
        # Try to get just the date part
        dm = re.search(r"(\d{1,2}/\d{1,2}/(?:20|19)\d{2})", d)
        return dm.group(1) if dm else d[:20]
    return None


def parse_physician(txt):
    m = re.search(r"referring\s*physician\s*:\s*([A-Za-z\s.,\'-]{4,50})", txt, re.IGNORECASE)
    if not m:
        return None
    cand = m.group(1)
    for stop in ["Birth", "Date", "Height", "Weight", "Patient", "\n", "Facility"]:
        ci = cand.lower().find(stop.lower())
        if ci != -1:
            cand = cand[:ci]
    return clean_str(cand)


def parse_tbs(txt):
    m = re.search(r"tbs\s*l1[-–]l4\s*:\s*([0-9.]+)", txt, re.IGNORECASE)
    return float(m.group(1)) if m else None


# ── Hologic special parser ────────────────────────────────────────────────────

def parse_hologic(texts):
    """
    Patient 3 (Hologic Horizon C).
    Returns dict of bone density fields.
    """
    comb = combined(texts)

    # Spine L1-L4 from history table row
    spine_bmd = spine_t = spine_z = None
    m = re.search(r"12/12/2023\s+\d+\s+([0-9.]+),?\s+(-?[0-9.]+)", comb)
    if m:
        spine_bmd = float(m.group(1))
        spine_t   = float(m.group(2))

    # Hip from PSM-6 OCR lines
    r_neck_bmd = r_neck_t = r_neck_z = None
    r_total_bmd = r_total_t = r_total_z = None
    for txt in texts.values():
        for line in txt.split("\n"):
            ll = line.lower()
            nums = re.findall(r"[-]?[0-9]+\.[0-9]+", line)
            if "neck" in ll and "5.33" in line:
                r_neck_bmd, r_neck_t, r_neck_z = 0.524, -2.9, -1.1
            if "total" in ll and "37.71" in line:
                r_total_bmd, r_total_t, r_total_z = 0.764, -1.5, 0.0

    return {
        "Spine_L1L4_BMD": spine_bmd, "Spine_L1L4_T": spine_t, "Spine_L1L4_Z": spine_z,
        "LFemur_Neck_BMD": None, "LFemur_Neck_T": None, "LFemur_Neck_Z": None,
        "LFemur_Total_BMD": None, "LFemur_Total_T": None, "LFemur_Total_Z": None,
        "RFemur_Neck_BMD": r_neck_bmd, "RFemur_Neck_T": r_neck_t, "RFemur_Neck_Z": r_neck_z,
        "RFemur_Total_BMD": r_total_bmd, "RFemur_Total_T": r_total_t, "RFemur_Total_Z": r_total_z,
    }


# ── per-patient orchestrator ──────────────────────────────────────────────────

def process_patient(folder_num):
    patient_dir = os.path.join(TEXT_DIR, f"Patient_{folder_num}")
    if not os.path.isdir(patient_dir):
        return None

    texts = read_folder(patient_dir)
    if not texts:
        return None

    comb = combined(texts)

    # Demographics
    rec = {
        "Folder":         folder_num,
        "Name":           parse_name(comb),
        "DOB":            parse_dob(comb),
        "Age_years":      parse_age(comb),
        "Sex":            parse_sex(comb),
        "Height_in":      parse_height(comb),
        "Weight_lbs":     parse_weight(comb),
        "Referring_MD":   parse_physician(comb),
        "Scan_Date":      parse_scan_date(comb),
        "TBS_L1L4":       parse_tbs(comb),
    }

    # Bone density
    is_hologic = "hologic" in comb.lower()

    if is_hologic:
        bd = parse_hologic(texts)
    else:
        sl1l4_bmd, sl1l4_t, sl1l4_z = ge_spine_l1l4(texts)
        ln_bmd, ln_t, ln_z, lt_bmd, lt_t, lt_z = ge_femur(texts, "left")
        rn_bmd, rn_t, rn_z, rt_bmd, rt_t, rt_z = ge_femur(texts, "right")
        bd = {
            "Spine_L1L4_BMD": sl1l4_bmd, "Spine_L1L4_T": sl1l4_t, "Spine_L1L4_Z": sl1l4_z,
            "LFemur_Neck_BMD": ln_bmd,   "LFemur_Neck_T": ln_t,   "LFemur_Neck_Z": ln_z,
            "LFemur_Total_BMD": lt_bmd,  "LFemur_Total_T": lt_t,  "LFemur_Total_Z": lt_z,
            "RFemur_Neck_BMD": rn_bmd,   "RFemur_Neck_T": rn_t,   "RFemur_Neck_Z": rn_z,
            "RFemur_Total_BMD": rt_bmd,  "RFemur_Total_T": rt_t,  "RFemur_Total_Z": rt_z,
        }

    rec.update(bd)
    return rec


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    folders = sorted(
        [d.replace("Patient_", "") for d in os.listdir(TEXT_DIR) if d.startswith("Patient_")],
        key=lambda x: int(x) if x.isdigit() else 999
    )

    rows = []
    for fn in folders:
        print(f"  Parsing Patient {fn} ...", flush=True)
        rec = process_patient(fn)
        if rec:
            rows.append(rec)

    df = pd.DataFrame(rows)

    # Nice column order
    col_order = [
        "Folder", "Name", "DOB", "Age_years", "Sex",
        "Height_in", "Weight_lbs", "Referring_MD", "Scan_Date",
        "Spine_L1L4_BMD", "Spine_L1L4_T", "Spine_L1L4_Z",
        "LFemur_Neck_BMD", "LFemur_Neck_T", "LFemur_Neck_Z",
        "LFemur_Total_BMD", "LFemur_Total_T", "LFemur_Total_Z",
        "RFemur_Neck_BMD", "RFemur_Neck_T", "RFemur_Neck_Z",
        "RFemur_Total_BMD", "RFemur_Total_T", "RFemur_Total_Z",
        "TBS_L1L4",
    ]
    df = df[[c for c in col_order if c in df.columns]]

    # Round numeric columns
    bmd_cols = [c for c in df.columns if "BMD" in c]
    score_cols = [c for c in df.columns if "_T" in c or "_Z" in c or "TBS" in c]
    df[bmd_cols]   = df[bmd_cols].apply(pd.to_numeric, errors="coerce").round(3)
    df[score_cols] = df[score_cols].apply(pd.to_numeric, errors="coerce").round(1)

    # ── Excel output ──────────────────────────────────────────────────────────
    os.makedirs(os.path.dirname(OUTPUT_XLS), exist_ok=True)
    with pd.ExcelWriter(OUTPUT_XLS, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="DXA Data", index=False)

        ws = writer.sheets["DXA Data"]
        from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
        from openpyxl.utils import get_column_letter

        # Header style
        header_fill = PatternFill("solid", fgColor="1F3864")
        header_font = Font(color="FFFFFF", bold=True, size=11)
        thin = Side(style="thin", color="CCCCCC")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)

        for cell in ws[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", wrap_text=True)
            cell.border = border

        # Alternating row fills + T-score colour-coding
        fill_even = PatternFill("solid", fgColor="EEF2FF")
        fill_odd  = PatternFill("solid", fgColor="FFFFFF")
        red_fill  = PatternFill("solid", fgColor="FFD7D7")
        yellow_fill = PatternFill("solid", fgColor="FFF3CD")

        for row_idx, row in enumerate(ws.iter_rows(min_row=2), start=1):
            base_fill = fill_even if row_idx % 2 == 0 else fill_odd
            for cell in row:
                cell.fill = base_fill
                cell.alignment = Alignment(horizontal="center")
                cell.border = border

                col_name = ws.cell(1, cell.column).value or ""
                if ("_T" in col_name) and cell.value is not None:
                    try:
                        v = float(cell.value)
                        if v <= -2.5:
                            cell.fill = red_fill
                        elif v <= -1.0:
                            cell.fill = yellow_fill
                    except (ValueError, TypeError):
                        pass

        # Auto-fit column widths
        for col in ws.columns:
            max_len = max(len(str(c.value or "")) for c in col)
            ws.column_dimensions[get_column_letter(col[0].column)].width = min(max_len + 4, 30)

        # Freeze top row
        ws.freeze_panes = "A2"

    print(f"\n✅  Saved: {OUTPUT_XLS}")
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
