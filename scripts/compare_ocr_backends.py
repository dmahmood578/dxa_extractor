#!/usr/bin/env python3
"""
Compare OCR backends (Tesseract text, Surya JSON, Paddle text) for a patient folder.
Usage: python scripts/compare_ocr_backends.py --folder 3 --out ocr_compare/patient_3/compare_summary.csv
"""
import argparse, os, re, json, glob
import pandas as pd

parser = argparse.ArgumentParser()
parser.add_argument('--folder', required=True)
parser.add_argument('--out', required=False, default=None)
args = parser.parse_args()
folder = str(args.folder)
base_dir = f'ocr_compare/patient_{folder}'
csvfile = 'data/patient_wide_measurements.csv'

# helpers
num_re = re.compile(r'(-?\d+\.\d+)')
t_re = re.compile(r'(-?\d+\.?\d*)')

def sane_bmd(s):
    try:
        v=float(s)
        return 0.1<=v<=3.0
    except Exception:
        return False

# load csv row by Folder
df = pd.read_csv(csvfile, dtype=str)
row = None
mask = df['Folder'].astype(str)==folder
if mask.sum()>0:
    row = df[mask].iloc[0].to_dict()

results = []
regions = ['Spine_L1L4','LFemur_Neck','RFemur_Neck']
# CSV values
if row:
    for r in regions:
        b = row.get(f'{r}_BMD','')
        t = row.get(f'{r}_T','')
        results.append({'region':r,'source':'CSV','bmd':b,'t':t,'note':''})

# Surya JSONs
surya_dir = os.path.join(base_dir,'surya')
for root,dirs,files in os.walk(surya_dir):
    for fname in files:
        if fname=='results.json':
            try:
                j=json.load(open(os.path.join(root,fname)))
            except Exception:
                continue
            for k,v in j.items():
                for page in v:
                    for block in page.get('blocks',[]):
                        html = block.get('html','') or ''
                        for table in re.findall(r'<table.*?>.*?</table>', html, flags=re.S|re.I):
                            # parse rows
                            trs = re.findall(r'<tr.*?>.*?</tr>', table, flags=re.S|re.I)
                            hdr=None
                            for i,tr in enumerate(trs[:3]):
                                if 'bmd' in tr.lower() or 't-score' in tr.lower() or 'region' in tr.lower():
                                    hdr=i; break
                            if hdr is None: continue
                            cols = []
                            for tr in trs[hdr:]:
                                cells = re.findall(r'<t[dh].*?>(.*?)</t[dh]>', tr, flags=re.S|re.I)
                                clean = [re.sub(r'<.*?>','',c).strip() for c in cells]
                                if not clean: continue
                                # first cell region
                                region = clean[0]
                                bmd=None; tscore=None
                                # try header mapping
                                for c in clean[1:]:
                                    m=num_re.search(c)
                                    if m and bmd is None:
                                        bmd=m.group(1)
                                    elif m and tscore is None:
                                        tscore=m.group(1)
                                if bmd and sane_bmd(bmd):
                                    results.append({'region':region,'source':'Surya','bmd':bmd,'t':tscore,'note':os.path.join(root,fname)})

# Paddle text files
paddle_dir = os.path.join(base_dir,'paddle')
for pfile in glob.glob(os.path.join(paddle_dir,'*','*.txt')):
    txt=open(pfile,encoding='utf-8').read()
    lines=[l.strip() for l in txt.splitlines() if l.strip()]
    for i,l in enumerate(lines):
        low=l.lower()
        for r in ['neck','total','spine']:
            if r in low:
                # look nearby lines for numbers
                window=' '.join(lines[max(0,i-2):i+3])
                m=num_re.search(window)
                mt=None
                if m:
                    b=m.group(1)
                    if sane_bmd(b):
                        mt = t_re.search(window)
                        tval = mt.group(1) if mt else ''
                        # decide region mapping
                        if 'neck' in low:
                            region = 'LFemur_Neck' if 'left' in low or 'l ' in low else 'LFemur_Neck'
                        elif 'total' in low:
                            region = 'Spine_L1L4'
                        else:
                            region = 'Spine_L1L4'
                        results.append({'region':region,'source':'Paddle','bmd':b,'t':tval,'note':pfile})

# Tesseract: extracted_text/Patient_{folder}/*.txt
tess_dir = f'extracted_text/Patient_{int(folder)}'
if os.path.isdir(tess_dir):
    for tfile in glob.glob(os.path.join(tess_dir,'*.txt')):
        txt=open(tfile,encoding='utf-8',errors='ignore').read()
        for line in txt.splitlines():
            low=line.lower()
            if any(k in low for k in ['neck','total','l1','l2','l3','l4','spine','bmd','t-score']):
                m=num_re.search(line)
                if m:
                    b=m.group(1)
                    if sane_bmd(b):
                        mt = t_re.search(line)
                        tval = mt.group(1) if mt else ''
                        reg='Spine_L1L4'
                        if 'neck' in low:
                            reg='LFemur_Neck'
                        results.append({'region':reg,'source':'Tesseract','bmd':b,'t':tval,'note':tfile})

# aggregate latest per source+region
agg = {}
for r in results:
    key=(r['region'], r['source'])
    if key not in agg:
        agg[key]=r

out_rows=[]
for (region,source),r in agg.items():
    out_rows.append({'region':region,'source':source,'bmd':r.get('bmd',''),'t':r.get('t',''),'note':r.get('note','')})

out_df = pd.DataFrame(out_rows)
if args.out:
    out_df.to_csv(args.out,index=False)
    print('Wrote', args.out)
print(out_df.to_string(index=False))
