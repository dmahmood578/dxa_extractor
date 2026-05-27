#!/usr/bin/env python3
"""
Merge Surya JSON OCR outputs into data/patient_wide_measurements.csv for a given patient name.
Usage: python scripts/merge_surya_to_csv.py --surya-dir ocr_compare/patient_3/surya --csv data/patient_wide_measurements.csv --name "Lynch, Lois A"
"""
import argparse
import json
import os
import re
import pandas as pd

parser = argparse.ArgumentParser()
parser.add_argument('--surya-dir', required=True)
parser.add_argument('--csv', required=True)
parser.add_argument('--name', required=False)
parser.add_argument('--folder', required=False, help='CSV Folder value to match')
args = parser.parse_args()

def extract_tables_from_html(html):
    # crude extraction: find <table ...>...</table> blocks
    tables = re.findall(r'<table.*?>.*?</table>', html, flags=re.S|re.I)
    return tables

def parse_table_html(table_html):
    # return list of rows, each row is list of cell texts
    # strip tags and extract <tr> blocks
    rows = []
    for tr in re.findall(r'<tr.*?>.*?</tr>', table_html, flags=re.S|re.I):
        cells = re.findall(r'<t[dh].*?>(.*?)</t[dh]>', tr, flags=re.S|re.I)
        # clean cell text
        clean = [re.sub(r'<.*?>', '', c).strip() for c in cells]
        if clean:
            rows.append(clean)
    return rows

# walk surya dir and collect numeric rows keyed by region label
regions = {}
for root, dirs, files in os.walk(args.surya_dir):
    for fname in files:
        if fname.endswith('results.json'):
            fpath = os.path.join(root, fname)
            try:
                j = json.load(open(fpath,'r'))
            except Exception:
                continue
            # j is dict with keys like ser_1_inst_1
            for k,v in j.items():
                for page in v:
                    for block in page.get('blocks',[]):
                        html = block.get('html','') or ''
                        for table_html in extract_tables_from_html(html):
                            rows = parse_table_html(table_html)
                            # find header row containing 'Region' or 'Area' or 'BMD'
                            header_idx = None
                            for i,r in enumerate(rows[:3]):
                                low = ' '.join(r).lower()
                                if 'region' in low or 'area' in low or 'bmd' in low:
                                    header_idx = i
                                    break
                            if header_idx is not None:
                                headers = rows[header_idx]
                                # determine indices for BMD and T columns
                                idx_bmd = None
                                idx_t = None
                                for i,h in enumerate(headers):
                                    hl = h.lower()
                                    if 'bmd' in hl and idx_bmd is None:
                                        idx_bmd = i
                                    if ('t-score' in hl or h.strip().lower()=='t' or 't score' in hl) and idx_t is None:
                                        idx_t = i
                                for data_row in rows[header_idx+1:]:
                                    if not data_row:
                                        continue
                                    region = data_row[0]
                                    bmd=None; tscore=None
                                    # use header indices if available
                                    if idx_bmd is not None and idx_bmd < len(data_row):
                                        bmd = re.sub(r'[^0-9\.-]','', data_row[idx_bmd]).strip() or None
                                    if idx_t is not None and idx_t < len(data_row):
                                        tscore = re.sub(r'[^0-9\.-]','', data_row[idx_t]).strip() or None
                                    # fallback: find numeric tokens (prefer decimals between 0 and 2)
                                    if bmd is None:
                                        for c in data_row:
                                            m=re.search(r'([0-9]+\.[0-9]+)', c)
                                            if m:
                                                bmd=m.group(1); break
                                    if tscore is None:
                                        # prefer negative or small numbers as T-score
                                        for c in data_row[::-1]:
                                            m=re.search(r'(-?\d+\.?\d*)', c)
                                            if m and m.group(1) != bmd:
                                                tscore=m.group(1); break
                                    # sanity checks: BMD typically between 0.3 and ~2.5
                                    try:
                                        if bmd is not None:
                                            if float(bmd) > 3.0 or float(bmd) < 0.1:
                                                bmd = None
                                    except Exception:
                                        pass
                                    # T-score should be within a reasonable range
                                    try:
                                        if tscore is not None:
                                            if abs(float(tscore)) > 15:
                                                tscore = None
                                    except Exception:
                                        pass
                                    regions[region.strip()] = {'bmd':bmd, 't':tscore, 'source': fpath}

# load csv
df = pd.read_csv(args.csv, dtype=str)
idx = None
if args.name:
    mask = df['PatientName'].str.contains(args.name, na=False)
    if mask.sum()>0:
        idx = df[mask].index[0]
        print('Found row by name', idx)
if idx is None and args.folder:
    mask = df['Folder'].astype(str)==str(args.folder)
    if mask.sum()>0:
        idx = df[mask].index[0]
        print('Found row by folder', idx)
if idx is None:
    print('No matching patient rows for', args.name or args.folder)
    raise SystemExit(1)
# map common region names to CSV columns
mapping = {
    'l1l4':'Spine_L1L4',
    'total':'Spine_L1L4',
    'neck':'LFemur_Neck',
    'left neck':'LFemur_Neck',
    'right neck':'RFemur_Neck',
}
# Update df for known mappings
for region,vals in regions.items():
    rlow = region.lower()
    if 'neck' in rlow and 'left' in rlow:
        colpref='LFemur_Neck'
    elif 'neck' in rlow and 'right' in rlow:
        colpref='RFemur_Neck'
    elif rlow.strip()=='neck':
        # ambiguous: prefer left unless left has an implausible existing value
        existing_left = None
        if 'LFemur_Neck_BMD' in df.columns:
            existing_left = df.at[idx,'LFemur_Neck_BMD']
        try:
            if existing_left is not None and existing_left != '' and not pd.isna(existing_left):
                if float(existing_left) > 3.0 or float(existing_left) < 0.1:
                    # clear implausible existing left
                    df.at[idx,'LFemur_Neck_BMD'] = ''
                    df.at[idx,'LFemur_Neck_T'] = '' if 'LFemur_Neck_T' in df.columns else None
                    existing_left = None
        except Exception:
            pass
        if existing_left is None:
            colpref='LFemur_Neck'
        else:
            colpref='RFemur_Neck'
    elif 'total' in rlow or 'spine' in rlow or 'l1' in rlow:
        colpref='Spine_L1L4'
    else:
        continue
    # ensure columns exist
    for suf,col in [( 'BMD', f'{colpref}_BMD'), ('T', f'{colpref}_T')]:
        if col not in df.columns:
            df[col]=''
    if vals.get('bmd'):
        df.at[idx, f'{colpref}_BMD'] = vals['bmd']
    if vals.get('t'):
        df.at[idx, f'{colpref}_T'] = vals['t']
    print('Wrote', colpref, '->', vals)

# backup csv
bak = args.csv + '.bak'
open(bak,'w').write(open(args.csv).read())
print('Backup written to', bak)
# write updated csv
df.to_csv(args.csv, index=False)
print('Updated', args.csv)
