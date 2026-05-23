import os

def search_text_files():
    directory = "dxa_extractor"
    txt_files = [f for f in os.listdir(directory) if f.endswith('_txt.txt')]
    print(f"Searching through {len(txt_files)} OCR text files...")
    
    keywords = ['ap spine', 'dualfemur', 'femur neck', 'neck', 'l1-l4', 'l1-l3', 'l2-l4', 'total', 'bmd', 't-score', 'z-score', 'tscore', 'zscore']
    
    for f in sorted(txt_files):
        path = os.path.join(directory, f)
        content = open(path, 'r').read().lower()
        matches = []
        for kw in keywords:
            if kw in content:
                matches.append(kw)
        if matches:
            print(f"{f}: matches={matches}")
            # print lines that contain the matches
            lines = content.split('\n')
            for l in lines:
                l_strip = l.strip()
                if any(kw in l_strip for kw in ['dualfemur', 'ap spine', 'l1-l4', 'neck', 'total', 'bmd']):
                    print(f"  Line: {l_strip[:120]}")

search_text_files()
