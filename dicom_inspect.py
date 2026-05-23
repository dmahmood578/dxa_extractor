import pydicom
import sys

def inspect_dicom(path):
    print("=" * 60)
    print(f"Inspecting: {path}")
    print("=" * 60)
    try:
        ds = pydicom.dcmread(path)
        print(f"SOP Class UID: {ds.SOPClassUID} ({getattr(ds, 'SOPClassUID', '').name})")
        print(f"Modality: {getattr(ds, 'Modality', 'N/A')}")
        print(f"Patient Name: {getattr(ds, 'PatientName', 'N/A')}")
        print(f"Patient ID: {getattr(ds, 'PatientID', 'N/A')}")
        
        # Print first few elements
        print("\n--- First 20 elements ---")
        count = 0
        for elem in ds:
            print(elem)
            count += 1
            if count >= 20:
                break
        
        # If there's pixel data
        if hasattr(ds, 'PixelData'):
            print("\nPixel Data: Present")
            print(f"Rows x Cols: {getattr(ds, 'Rows', 'N/A')} x {getattr(ds, 'Columns', 'N/A')}")
            print(f"Bits Allocated: {getattr(ds, 'BitsAllocated', 'N/A')}")
        else:
            print("\nPixel Data: NOT Present")
            
        # Check for SR document content
        if hasattr(ds, 'ContentSequence'):
            print("\nContent Sequence (SR): Present")
            print(f"Length: {len(ds.ContentSequence)}")
            # print a bit of ContentSequence
            for idx, item in enumerate(ds.ContentSequence[:5]):
                print(f"Item {idx}: {item}")
    except Exception as e:
        print(f"Error reading: {e}")

inspect_dicom("CLD DXA/1/DICOM/000061C8/AA9059FF/AA9D2FAE/0000F512/FFCAAB8E")
inspect_dicom("CLD DXA/1/DICOM/000061C8/AA9059FF/AA9D2FAE/00000241/EE4B361C")
