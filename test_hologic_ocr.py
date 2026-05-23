import subprocess
import os

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def test_psms():
    img_path = os.path.join(_SCRIPT_DIR, "extracted_images", "Patient_3", "ser_2_inst_1.png")
    if not os.path.exists(img_path):
        print(f"Image not found at {img_path}")
        return
        
    tess_path = 'tesseract'
    
    # We will test PSM 4, 6, 11, and 12
    for psm in [3, 4, 6, 11, 12]:
        out_base = os.path.join(_SCRIPT_DIR, f"test_psm_{psm}")
        print(f"\n--- Running OCR with --psm {psm} ---")
        try:
            subprocess.run([tess_path, img_path, out_base, '--psm', str(psm)], 
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            txt_path = out_base + '.txt'
            if os.path.exists(txt_path):
                content = open(txt_path, 'r').read().strip()
                # Print lines containing "Neck", "Total", "Spine", or some numbers
                lines = content.split('\n')
                print(f"Total lines extracted: {len(lines)}")
                print("First 15 lines:")
                for l in lines[:15]:
                    print(f"  {l.strip()}")
                
                # Check for "Total" or "Neck"
                print("Matches:")
                for idx, l in enumerate(lines):
                    if any(kw in l.lower() for kw in ['neck', 'total', 'troch', 'inter']):
                        print(f"  Line {idx+1:02d}: {l.strip()}")
            else:
                print(f"Failed to generate output for psm {psm}")
        except Exception as e:
            print(f"Error: {e}")

test_psms()
