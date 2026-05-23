import pydicom

def inspect_private_tags(path):
    print("=" * 60)
    print(f"Inspecting tags in: {path}")
    print("=" * 60)
    try:
        ds = pydicom.dcmread(path)
        for elem in ds:
            # Check if tag is private (group number is odd)
            is_private = elem.tag.group % 2 != 0
            # Or check standard tags that might have long string values
            is_long_string = elem.VR in ['LT', 'ST', 'UT', 'OB', 'OW']
            
            if is_private or is_long_string:
                val = elem.value
                val_str = ""
                if isinstance(val, bytes):
                    # Try decoding as ASCII/UTF-8
                    try:
                        decoded = val.decode('utf-8', errors='ignore')
                        # If it contains readable words or XML, print it
                        readable = ''.join(c if (32 <= ord(c) < 127 or c in '\n\r\t') else ' ' for c in decoded)
                        words = readable.split()
                        if len(words) > 5:
                            val_str = f"BYTES-DECODED (words={len(words)}): {readable[:300]}..."
                    except Exception:
                        pass
                else:
                    val_str = str(val)
                
                if val_str:
                    print(f"Tag: {elem.tag} ({elem.keyword or 'Private'}) VR: {elem.VR} - {val_str[:500]}")
    except Exception as e:
        print(f"Error: {e}")

inspect_private_tags("CLD DXA/1/DICOM/000061C8/AA9059FF/AA9D2FAE/00000241/EE4B361C")
