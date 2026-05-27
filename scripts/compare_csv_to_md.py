#!/usr/bin/env python3
"""
Convert compare_summary.csv into a short markdown summary for a patient.
Usage: python scripts/compare_csv_to_md.py --csv ocr_compare/patient_3/compare_summary.csv --out ocr_compare/patient_3/compare_summary.md
"""
import argparse, pandas as pd
parser = argparse.ArgumentParser()
parser.add_argument('--csv', required=True)
parser.add_argument('--out', required=False, default=None)
args = parser.parse_args()

df = pd.read_csv(args.csv, dtype=str)
# simple markdown grouping
md_lines = []
md_lines.append('# OCR Comparison Summary')
md_lines.append('')
for region in df['region'].unique():
    sub = df[df['region']==region]
    md_lines.append(f'## {region}')
    md_lines.append('')
    md_lines.append('| Source | BMD | T-score | Note |')
    md_lines.append('|---|---:|---:|---|')
    for _,r in sub.iterrows():
        note = r.get('note','') if r.get('note', '')==r.get('note', '') else ''
        md_lines.append(f"| {r.get('source','')} | {r.get('bmd','')} | {r.get('t','')} | {note} |")
    md_lines.append('')

out = '\n'.join(md_lines)
if args.out:
    open(args.out,'w',encoding='utf-8').write(out)
    print('Wrote', args.out)
else:
    print(out)
