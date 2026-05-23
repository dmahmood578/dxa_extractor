import os
import pydicom

def dump_all_srs():
    sr_paths = []
    for root, dirs, files in os.walk('CLD DXA'):
        for f in files:
            if f.startswith('.'):
                continue
            path = os.path.join(root, f)
            try:
                ds = pydicom.dcmread(path, stop_before_pixels=True)
                if getattr(ds, 'Modality', '') == 'SR':
                    sr_paths.append(path)
            except Exception:
                pass
                
    print(f"Found {len(sr_paths)} SR files.")
    for idx, path in enumerate(sr_paths):
        print(f"\n--- SR FILE {idx+1}: {path} ---")
        try:
            ds = pydicom.dcmread(path)
            # Find any tag that contains numbers or strings that look like measurements
            for elem in ds:
                if elem.tag.group % 2 != 0: # private
                    print(f"  Private: {elem.tag} {elem.keyword} ({elem.VR}) = {elem.value}")
                elif elem.VR in ['ST', 'LT', 'UT', 'DS', 'FL', 'FD', 'IS', 'LO', 'SH']:
                    # Print if it looks interesting (skip standard UIDs or dates unless they are relevant)
                    if elem.keyword not in ['SOPClassUID', 'SOPInstanceUID', 'StudyInstanceUID', 'SeriesInstanceUID']:
                        print(f"  {elem.keyword} ({elem.VR}): {elem.value}")
                elif elem.VR == 'SQ':
                    print(f"  Sequence: {elem.keyword} ({len(elem.value)} items)")
                    # show some sequence details
                    for i, item in enumerate(elem.value):
                        for sub_elem in item:
                            if sub_elem.VR in ['ST', 'LT', 'UT', 'DS', 'FL', 'FD', 'IS', 'LO', 'SH']:
                                print(f"    Item {i} - {sub_elem.keyword} ({sub_elem.VR}): {sub_elem.value}")
        except Exception as e:
            print(f"  Error reading: {e}")

dump_all_srs()
