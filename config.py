import os

class Config:
    # Camera Settings
    CAMERA_INDEX = 0
    CAMERA_WIDTH = 320 # Optimized for low-resource CPUs
    CAMERA_HEIGHT = 240
    FPS = 24 # Standard cinematic FPS, lighter on CPU

    # Model Settings
    MODEL_ASSET_PATH = 'hand_landmarker.task'
    NUM_HANDS = 1
    MIN_HAND_DETECTION_CONFIDENCE = 0.55 # Lowered for grainy old webcams
    MIN_HAND_PRESENCE_CONFIDENCE = 0.55
    MIN_TRACKING_CONFIDENCE = 0.55
    MODEL_COMPLEXITY = 0 # Lite is best for old CPUs

    # Gesture Logic
    GESTURE_STABILITY_FRAMES = 2  # Faster response on low-fps hardware
    ACTION_COOLDOWN = 0.6
    
    # UI Settings
    DRAW_LANDMARKS = True
    THEME_COLOR = (255, 165, 0) # BGR (Orange)

    # Paths
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    GESTURES_FILE = os.path.join(BASE_DIR, 'gestures.json')
    SEQUENCES_FILE = os.path.join(BASE_DIR, 'sequences.json')
    FRONTEND_DIR = os.path.join(BASE_DIR, 'frontend')

    # Logging
    LOG_LEVEL = "WARNING"
