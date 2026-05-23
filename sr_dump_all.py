import pydicom

def dump_all_elements(path):
    print("=" * 60)
    print(f"Dumping All Elements: {path}")
    print("=" * 60)
    try:
        ds = pydicom.dcmread(path)
        for elem in ds:
            # If sequence, print its name and size, but not full contents to avoid excessive output
            if elem.VR == 'SQ':
                print(f"{elem.tag} {elem.keyword} ({elem.VR}): Sequence with {len(elem.value)} items")
                for i, item in enumerate(elem.value):
                    print(f"  Item {i}:")
                    for sub_elem in item:
                        if sub_elem.VR == 'SQ':
                            print(f"    {sub_elem.tag} {sub_elem.keyword} ({sub_elem.VR}): Subsequence")
                        else:
                            print(f"    {sub_elem.tag} {sub_elem.keyword} ({sub_elem.VR}): {sub_elem.value}")
            else:
                print(f"{elem.tag} {elem.keyword} ({elem.VR}): {elem.value}")
    except Exception as e:
        print(f"Error reading: {e}")

dump_all_elements("CLD DXA/1/DICOM/000061C8/AA9059FF/AA9D2FAE/0000F512/FFCAAB8E")
