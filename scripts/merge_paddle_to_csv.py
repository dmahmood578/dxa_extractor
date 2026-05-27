#!/usr/bin/env python3
"""
Merge Paddle JSON OCR outputs into data/patient_wide_measurements.csv for a given patient folder.
Usage: python scripts/merge_paddle_to_csv.py --paddle-dir ocr_compare/patient_3/paddle --csv data/patient_wide_measurements.csv --folder 3
"""
import argparse, os, json, re
import pandas as pd

parser = argparse.ArgumentParser()
parser.add_argument('--paddle-dir', required=True)
parser.add_argument('--csv', required=True)
parser.add_argument('--folder', required=True)
args = parser.parse_args()

# collect candidates from paddle json files
regions = {}
for root, dirs, files in os.walk(args.paddle_dir):
    for fname in files:
        if fname.endswith('.json'):
            fpath = os.path.join(root, fname)
            try:
                j = json.load(open(fpath,'r'))
            except Exception:
                continue
            for cand in j.get('candidates',[]):
                region_label = cand.get('region','').strip()
                bmd = cand.get('bmd')
                t = cand.get('t')
                if not bmd:
                    continue
                try:
                    fv = float(bmd)
                    if fv < 0.1 or fv > 3.0:
                        continue
                except Exception:
                    continue
                # normalize region mapping
                rl = region_label.lower()
                if 'neck' in rl:
                    key = 'Neck'
                elif 'spine' in rl or 'l1' in rl or 'total' in rl:
                    key = 'Spine'
                else:
                    key = region_label or 'Unknown'
                # prefer first valid candidate per key
                if key not in regions:
                    regions[key] = {'bmd': bmd, 't': t, 'source': fpath}

# load csv and find row by folder
df = pd.read_csv(args.csv, dtype=str)
idx = None
mask = df['Folder'].astype(str)==str(args.folder)
if mask.sum()>0:
    idx = df[mask].index[0]
    print('Found row by folder', idx)
else:
    print('No matching row for Folder', args.folder)
    raise SystemExit(1)

# map keys to columns
for key, vals in regions.items():
    if key=='Neck':
        # ambiguous: write both LFemur and RFemur if one empty
        for colpref in ['LFemur_Neck','RFemur_Neck']:
            for suf,col in [('BMD', f'{colpref}_BMD'), ('T', f'{colpref}_T')]:
                if col not in df.columns:
                    df[col]=''
            if vals.get('bmd'):
                # only write if empty or implausible existing
                existing = df.at[idx, f'{colpref}_BMD'] if f'{colpref}_BMD' in df.columns else ''
                write = False
                try:
                    if existing is None or existing=='' or float(existing) < 0.1 or float(existing) > 3.0:
                        write = True
                except Exception:
                    write = True
                if write:
                    df.at[idx, f'{colpref}_BMD'] = vals['bmd']
                if vals.get('t'):
                    df.at[idx, f'{colpref}_T'] = vals['t']
                print('Wrote', colpref, vals)
                break
    elif key=='Spine':
        colpref='Spine_L1L4'
        for suf,col in [('BMD', f'{colpref}_BMD'), ('T', f'{colpref}_T')]:
            if col not in df.columns:
                df[col]=''
        if vals.get('bmd'):
            df.at[idx, f'{colpref}_BMD'] = vals['bmd']
        if vals.get('t'):
            df.at[idx, f'{colpref}_T'] = vals['t']
        print('Wrote', colpref, vals)
    else:
        print('Skipping unknown region', key)

# backup csv
bak = args.csv + '.bak_paddle'
open(bak,'w').write(open(args.csv).read())
print('Backup written to', bak)
# write updated csv
df.to_csv(args.csv, index=False)
print('Updated', args.csv)
