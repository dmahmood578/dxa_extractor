import os
import pydicom

def find_and_inspect_dxa():
    dxa_files = []
    for root, dirs, files in os.walk('CLD DXA'):
        for f in files:
            if f.startswith('.'):
                continue
            path = os.path.join(root, f)
            try:
                ds = pydicom.dcmread(path, stop_before_pixels=True)
                mod = getattr(ds, 'Modality', 'UNKNOWN')
                if mod == 'DXA':
                    dxa_files.append((path, ds))
            except Exception:
                pass
                
    print(f"Found {len(dxa_files)} DXA files.")
    if len(dxa_files) == 0:
        return
        
    path, ds = dxa_files[0]
    print(f"\nInspecting first DXA file: {path}")
    print("=" * 60)
    
    # Print all tags in the DXA file to see what variables we have
    for elem in ds:
        # Avoid printing pixel data
        if elem.VR == 'OB' or elem.VR == 'OW' or elem.keyword == 'PixelData':
            print(f"{elem.tag} {elem.keyword} ({elem.VR}): [PIXEL/BINARY DATA]")
        elif elem.VR == 'SQ':
            print(f"{elem.tag} {elem.keyword} ({elem.VR}): Sequence with {len(elem.value)} items")
        else:
            print(f"{elem.tag} {elem.keyword} ({elem.VR}): {elem.value}")

find_and_inspect_dxa()
