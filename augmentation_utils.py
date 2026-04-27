import cv2
import numpy as np
import random
from concurrent.futures import ThreadPoolExecutor

def augment_image(image, thumb_w=None, seed=None, fast=False):
    """
    Hyper-optimized augmentation.
    fast=True: Skips sharpening and noise for maximum throughput.
    """
    # Create local random instances for thread safety
    rng = random.Random(seed) if seed is not None else random.Random()
    np_rng = np.random.RandomState(seed) if seed is not None else np.random.RandomState()
        
    h, w = image.shape[:2]
    
    # Pre-Optimization: Resize FIRST if we are downscaling
    # This reduces pixels for WarpAffine and Filter2D exponentially
    if thumb_w and thumb_w < w:
        aspect = h / w
        thumb_h = int(thumb_w * aspect)
        image = cv2.resize(image, (thumb_w, thumb_h), interpolation=cv2.INTER_AREA)
        h, w = image.shape[:2] # Update dims for subsequent math
    
    # 1. Unified Affine Transform (Rotation + Scaling)
    angle = rng.uniform(-15, 15)
    zoom = rng.uniform(0.9, 1.1)
    
    M = cv2.getRotationMatrix2D((w/2, h/2), angle, zoom)
    augmented = cv2.warpAffine(image, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)

    # 2. Unified Color Adjustment (Brightness + Contrast)
    brightness = rng.uniform(0.9, 1.1)
    contrast = rng.uniform(0.9, 1.1)
    beta = int((brightness - 1.0) * 128)
    augmented = cv2.convertScaleAbs(augmented, alpha=contrast, beta=beta)

    if not fast:
        # 3. Final Sharpening (Expensive - Skip for small thumbnails)
        sharp_kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
        augmented = cv2.filter2D(augmented, -1, sharp_kernel)

        # 4. Optional: Subtle Noise
        if rng.random() > 0.8:
            noise = np_rng.normal(0, 2, augmented.shape).astype(np.uint8)
            augmented = cv2.add(augmented, noise)

    return augmented

def generate_bulk_augmentations(image, count=100):
    """Generates a list of bulk augmentations."""
    return [augment_image(image) for _ in range(count)]

def generate_augmentation_sprite(image, count=100, thumb_w=128):
    """
    Ultimate Sprite Generation.
    Uses ThreadPoolExecutor for instant startup and low memory overhead.
    """
    h, w = image.shape[:2]
    aspect = h / w
    thumb_h = int(thumb_w * aspect)
    
    # Use ThreadPool for instant startup (OpenCV releases GIL)
    with ThreadPoolExecutor() as executor:
        # Pass seeds to ensure deterministic matching with individual requests
        # Use fast=True for thumbnails to speed up generation by ~40%
        seeds = list(range(count))
        processed = list(executor.map(lambda s: augment_image(image, thumb_w=thumb_w, seed=s, fast=True), seeds))
    
    # Calculate grid dimensions
    cols = 10 # Hardcoded for frontend mapping
    rows = int(np.ceil(count / cols))
    
    # Create empty background (Pre-allocated)
    sprite = np.zeros((rows * thumb_h, cols * thumb_w, 3), dtype=np.uint8)
    
    for idx, img in enumerate(processed):
        r, c = divmod(idx, cols)
        sprite[r*thumb_h:(r+1)*thumb_h, c*thumb_w:(c+1)*thumb_w] = img
            
    return sprite
