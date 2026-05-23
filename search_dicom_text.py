import os
import pydicom

def search_dicom_for_text():
    print("Searching all DICOM files for clinical keywords in headers...")
    keywords = ['bmd', 't-score', 'z-score', 'femur', 'spine', 'neck', 'l1', 'l2', 'l3', 'l4', 'lunar', 'hologic']
    found_matches = []
    
    for root, dirs, files in os.walk('CLD DXA'):
        for f in files:
            if f.startswith('.'):
                continue
            path = os.path.join(root, f)
            try:
                ds = pydicom.dcmread(path)
                for elem in ds:
                    if elem.VR in ['ST', 'LT', 'UT', 'LO', 'SH', 'PN']:
                        val_str = str(elem.value).lower()
                        for kw in keywords:
                            if kw in val_str:
                                found_matches.append((path, elem.tag, elem.keyword, kw, str(elem.value)))
            except Exception:
                pass
                
    print(f"Found {len(found_matches)} header string matches.")
    # Print the first 20 unique matches
    unique_matches = set()
    printed = 0
    for match in found_matches:
        key = (match[2], match[3], match[4][:100])
        if key not in unique_matches:
            unique_matches.add(key)
            print(f"File: {match[0]}\n  Tag: {match[1]} ({match[2]})\n  Keyword match: '{match[3]}'\n  Value: {match[4][:200]}")
            print("-" * 50)
            printed += 1
            if printed >= 20:
                break

search_dicom_for_text()
