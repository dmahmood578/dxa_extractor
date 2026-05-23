import os
import pydicom

def scan_all_dicoms(directory):
    print(f"Scanning all DICOM files in {directory}...")
    sr_files = []
    ot_files = []
    other_files = []
    
    for root, dirs, files in os.walk(directory):
        for f in files:
            path = os.path.join(root, f)
            # Skip hidden files
            if f.startswith('.'):
                continue
            try:
                # Try reading header
                ds = pydicom.dcmread(path, stop_before_pixels=True)
                modality = getattr(ds, 'Modality', 'UNKNOWN')
                if modality == 'SR':
                    sr_files.append((path, ds))
                elif modality == 'OT':
                    ot_files.append((path, ds))
                else:
                    other_files.append((path, ds, modality))
            except Exception:
                # Not a DICOM file or error reading
                pass
                
    print(f"Found {len(sr_files)} SR files, {len(ot_files)} OT files, and {len(other_files)} other DICOM files.")
    
    # Now let's inspect what's inside the SR files.
    # Are there any tags that have text or sequences?
    print("\n--- Inspecting first few SR files ---")
    for i, (path, ds) in enumerate(sr_files[:5]):
        print(f"\nSR File {i+1}: {path}")
        # Search for any text or sequence that might contain bone density numbers
        # Let's see if we can find 'ContentSequence' or private elements
        has_content_seq = 'ContentSequence' in ds
        print(f"  Has ContentSequence: {has_content_seq}")
        if has_content_seq:
            print(f"  ContentSequence Length: {len(ds.ContentSequence)}")
        
        # Let's search for tags containing 'Sequence' or tags in group 0040
        seqs = [elem.keyword for elem in ds if elem.VR == 'SQ']
        print(f"  Sequences present: {seqs}")
        
        # Check if there are private blocks or other attributes
        for elem in ds:
            if elem.tag.group == 0x0040:
                print(f"  Tag 0040 element: {elem.tag} {elem.keyword} ({elem.VR})")
                
scan_all_dicoms("CLD DXA")
