from PIL import Image
import numpy as np
import os

def check_images(directory):
    for f in sorted(os.listdir(directory)):
        if f.endswith('.png'):
            path = os.path.join(directory, f)
            try:
                img = Image.open(path)
                arr = np.array(img)
                print(f"{f}: shape={arr.shape}, min={arr.min()}, max={arr.max()}, mean={arr.mean():.2f}, unique_values={len(np.unique(arr))}")
            except Exception as e:
                print(f"{f}: Error: {e}")

check_images("dxa_extractor/extracted_images/1")
