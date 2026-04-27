import os
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'  # 0=all, 1=no INFO, 2=no WARNING, 3=no ERROR
import cv2
import time
import json
import threading
import mediapipe as mp
import logging
import numpy as np
from flask import Flask, render_template, Response, jsonify, request, send_from_directory, stream_with_context
from flask_cors import CORS
from urllib.parse import quote
from werkzeug.utils import secure_filename
from pypdf import PdfReader, PdfWriter

from config import Config
from gesture_engine import GestureEngine
from action_map import ActionMap
from draw_utils import draw_styled_landmarks
from augmentation_utils import augment_image, generate_bulk_augmentations, generate_augmentation_sprite
from attendance_manager import AttendanceManager
from notification_engine import NotificationEngine

# --- Configure Logging ---
# --- Configure Logging ---
logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL),
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler("server.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- Flask Setup ---
app = Flask(__name__, static_folder='frontend', static_url_path='')
CORS(app)

# Suppression
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

# --- Global State ---
class AppState:
    def __init__(self):
        self.lock = threading.Lock()
        
        self.mode = "DETECT" # DETECT, RECORD, ATTENDANCE, IDLE
        self.domain = "HUB" # HUB, OFFICE, MEDICAL, INDUSTRIAL, PRESENTATION
        
        # Action Queue for zero-latency processing
        self.action_queue = []
        self._start_action_worker()
        
        # Camera Data
        self.latest_frame_jpg = None
        self.latest_landmarks = None # Raw MP landmarks
        self.camera_active = True
        
        # Gesture Logic
        self.current_gesture = None
        self.last_action_name = "Ready"
        self.last_action_time = 0
        self.last_continuous_action_time = 0 # SEPARATE TIMESTAMP for continuous actions
        self.cooldown = 0.8 # reduced for better feel
        self.stability_threshold = 8 # reduced for better responsiveness
        self.last_triggered_gesture = None # Track for single-trigger logic
        
        # Engines
        self.engine = GestureEngine()
        self.action_map = ActionMap()
        self.attendance_mgr = AttendanceManager()
        self.notification_engine = NotificationEngine()
        self.landmarker = None  # Fixed typo from lanmarker
        self.start_time = time.time()
        
        # Stats
        self.fps = 0
        self.stability_score = 0
        self.theme = "DEFAULT"
        self._desktop_window = None # Reference to pywebview window
        
        # Training Metrics (Live Feedback)
        self.training_metrics = {
            "brightness": 0,
            "size": 0,
            "angle": 0,
            "size_range": [1.0, 0.0], # [min, max]
            "angle_range": [1.0, 0.0]  # [min, max]
        }
        
        # Dynamic Camera Settings
        self.camera_config = {
            "width": Config.CAMERA_WIDTH,
            "height": Config.CAMERA_HEIGHT,
            "fps": Config.FPS
        }
        self.camera_needs_update = False
        self.auto_gamma = True
        self.floating_camera_active = False # Track if desktop float window is open
    
    def _start_action_worker(self):
        def worker():
            while True:
                if self.action_queue:
                    action_data = self.action_queue.pop(0)
                    func = action_data['func']
                    args = action_data.get('args', [])
                    kwargs = action_data.get('kwargs', {})
                    try:
                        func(*args, **kwargs)
                    except Exception as e:
                        logger.error(f"Action Worker Error: {e}")
                time.sleep(0.01)
        threading.Thread(target=worker, daemon=True).start()

state = AppState()

# --- Background Thread: Camera & Processing ---
camera_thread_started = False

def init_landmarker():
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision
    
    try:
        # --- INDUSTRIAL UPGRADE: Absolute Path Resolution ---
        model_path = Config.MODEL_ASSET_PATH
        if not os.path.isabs(model_path):
            model_path = os.path.join(Config.BASE_DIR, model_path)
            
        logger.info(f"Loading MediaPipe model from: {model_path}")
        
        base_options = python.BaseOptions(model_asset_path=model_path)
        options = vision.HandLandmarkerOptions(
            base_options=base_options,
            num_hands=Config.NUM_HANDS,
            min_hand_detection_confidence=Config.MIN_HAND_DETECTION_CONFIDENCE,
            min_hand_presence_confidence=Config.MIN_HAND_PRESENCE_CONFIDENCE,
            min_tracking_confidence=Config.MIN_TRACKING_CONFIDENCE,
            running_mode=vision.RunningMode.VIDEO)
        return vision.HandLandmarker.create_from_options(options)
    except Exception as e:
        logger.critical(f"Failed to initialize MediaPipe Landmarker: {e}")
        return None

class SmoothedLM:
    __slots__ = ['x', 'y', 'z']
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z

class CameraStream:
    def __init__(self, src=0):
        self.src = src
        self.stream = self._open_camera(src)
        self.grabbed, self.frame = self.stream.read()
        self.stopped = False
        self.lock = threading.Lock()
        self.consecutive_failures = 0
        self.frame_id = 0

    def _open_camera(self, src):
        # Prefer DSHOW on Windows for better reliability and faster failure detection
        # MSMF often 'opens' but fails to 'read' or hangs the driver on some hardware.
        stream = cv2.VideoCapture(src, cv2.CAP_DSHOW)
        if not stream.isOpened():
             # Fallback to MSMF only if DSHOW strictly fails
             stream = cv2.VideoCapture(src, cv2.CAP_MSMF)
             
        if stream.isOpened():
            stream.set(cv2.CAP_PROP_FRAME_WIDTH, Config.CAMERA_WIDTH)
            stream.set(cv2.CAP_PROP_FRAME_HEIGHT, Config.CAMERA_HEIGHT)
            stream.set(cv2.CAP_PROP_FPS, Config.FPS)
            stream.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return stream

    def start(self):
        threading.Thread(target=self.update, daemon=True).start()
        return self

    def update(self):
        while not self.stopped:
            try:
                with self.lock:
                    grabbed, frame = self.stream.read()
                    self.grabbed = grabbed
                    if grabbed:
                        self.frame = frame.copy()
                        self.frame_id += 1
                        self.consecutive_failures = 0
                
                if not grabbed:
                    self.consecutive_failures += 1
                    time.sleep(0.1)
                    # Aggressive reconnect if stuck
                    if self.consecutive_failures > 5:
                        logger.warning("Camera stream stuck. Attempting hard hardware reset (DSHOW preferred)...")
                        self.stream.release()
                        time.sleep(1.5) # Give hardware time to release
                        self.stream = self._open_camera(self.src)
                        self.consecutive_failures = 0
                else:
                    time.sleep(0.01)
            except Exception as e:
                logger.error(f"Camera thread error: {e}")
                time.sleep(1)

    def read(self):
        with self.lock:
            return self.grabbed, self.frame, self.frame_id

    def set_config(self, width, height, fps):
        with self.lock:
            self.stream.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.stream.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            self.stream.set(cv2.CAP_PROP_FPS, fps)
            self.stream.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    def release(self):
        self.stopped = True
        with self.lock:
            self.stream.release()

    def isOpened(self):
        return self.stream.isOpened()

def camera_loop():
    global camera_thread_started
    if camera_thread_started:
        logger.warning("Camera loop already running! Skipping duplicate start.")
        return
    camera_thread_started = True

    logger.info("Starting Camera Loop...")
    
    state.landmarker = init_landmarker()
    if not state.landmarker:
        return

    # Stabilization
    pending_gesture = None
    stability_count = 0
    # Dynamic stability based on mode - Presentation mode needs to be SNAPPY
    def get_required_stability():
        return 1 if state.mode == "PRESENTATION" else Config.GESTURE_STABILITY_FRAMES

    # Auto-detect camera
    camera_index = Config.CAMERA_INDEX
    cap = CameraStream(camera_index)
    
    if not cap.isOpened():
        logger.warning(f"Default camera {camera_index} failed. Searching for others...")
        for i in range(5):
             if i == camera_index: continue
             cap = CameraStream(i)
             if cap.isOpened():
                 logger.info(f"Found working camera at index {i}")
                 camera_index = i
                 break
    
    if not cap.isOpened():
        logger.critical("NO CAMERA FOUND! Please connect a camera.")
        return
        
    cap.start()
    
    loop_start = time.time()
    last_processed_frame_id = -1
    last_timestamp = -1

    while True:
        if not state.camera_active:
            time.sleep(0.1)
            continue
            
        # Dynamic Reconfiguration
        if state.camera_needs_update:
            logger.info("Reconfiguring camera settings...")
            with state.lock:
                conf = state.camera_config
                state.camera_needs_update = False
            
            cap.set_config(conf['width'], conf['height'], conf['fps'])
            logger.info(f"Camera reconfigured: {conf}")
            
        success, frame, frame_id = cap.read()
        if not success or frame is None:
            time.sleep(0.1)
            continue
            
        if frame_id == last_processed_frame_id:
            time.sleep(0.005)
            continue
            
        last_processed_frame_id = frame_id

        # Flip
        frame = cv2.flip(frame, 1)
        
        # --- PERFORMANCE UPGRADE: Auto-Gamma (Low Light) ---
        if state.auto_gamma:
            # Use mean brightness to determine if we need a boost
            avg_brightness = np.mean(frame)
            if avg_brightness < 80: # Dark room
                gamma = 1.5 
                invGamma = 1.0 / gamma
                table = np.array([((i / 255.0) ** invGamma) * 255 for i in np.arange(0, 256)]).astype("uint8")
                frame = cv2.LUT(frame, table)
        
        # Process
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
        
        timestamp = int((time.time() - state.start_time) * 1000)
        # Ensure monotonic increment to prevent MediaPipe unhandled crash
        if timestamp <= last_timestamp:
            timestamp = last_timestamp + 1
        last_timestamp = timestamp
        
        # --- PERFORMANCE UPGRADE: Inference Skipping for Old CPUs ---
        # Only run detection every 2nd frame to save CPU
        if frame_id % 2 == 0:
            try:
                result = state.landmarker.detect_for_video(mp_image, timestamp)
            except Exception as e:
                logger.error(f"Inference error: {e}")
                pass
        else:
            # Reuse previous result if skipping (for logic stability)
            if 'result' not in locals(): result = None
        
        # Update State safely
        with state.lock:
            state.latest_landmarks = None
            
            if 'result' in locals() and result and result.hand_landmarks:
                raw_landmarks = result.hand_landmarks[0]
                
                # --- ULTIMATE UPGRADE: Kalman Smoothing ---
                flat_lms = np.array([[lm.x, lm.y, lm.z] for lm in raw_landmarks]).flatten()
                smoothed_flat = state.engine.kalman.update(flat_lms)
                
                # Rebuild smoothed landmarks for draw/logic
                state.latest_landmarks = []
                for i in range(21):
                    idx = i * 3
                    state.latest_landmarks.append(SmoothedLM(smoothed_flat[idx], smoothed_flat[idx+1], smoothed_flat[idx+2]))
                
                # Draw
                try:
                    # Use the smoothed landmarks we just created for the visual feed
                    frame = draw_styled_landmarks(frame, theme=state.theme, manual_landmarks=[state.latest_landmarks])
                except Exception as e:
                    logger.error(f"Drawing error: {e}")
                
                # Logic
                if state.mode == "DETECT":
                    # 1. Static Check
                    candidate = state.engine.find_gesture(state.latest_landmarks)
                    
                    if candidate == pending_gesture:
                        stability_count += 1
                    else:
                        pending_gesture = candidate
                        stability_count = 0
                    
                    if stability_count >= get_required_stability():
                         confirmed_gesture = pending_gesture
                    else:
                         confirmed_gesture = None

                    state.current_gesture = confirmed_gesture
                    
                    # 3. Consistently Stable Filter (Consensus)
                    if not hasattr(state, 'consensus_buffer'):
                        state.consensus_buffer = []
                    
                    state.consensus_buffer.append(confirmed_gesture)
                    if len(state.consensus_buffer) > 5:
                        state.consensus_buffer.pop(0)
                    
                    # Only confirm if most recent frames agree
                    counts = {}
                    for g in state.consensus_buffer:
                        counts[g] = counts.get(g, 0) + 1
                    
                    # Most frequent element
                    consensus_gesture = max(counts, key=counts.get) if counts else None
                    if counts.get(consensus_gesture, 0) >= 3: # 3/5 agreement
                         state.current_gesture = consensus_gesture
                    else:
                         state.current_gesture = None
                    
                    # 2. Dynamic Check (Parallel-ish)
                    if not confirmed_gesture:
                        # Append to history (we are already in a lock here)
                        if not hasattr(state, 'landmark_history'):
                            state.landmark_history = []
                        state.landmark_history.append(state.latest_landmarks)
                        if len(state.landmark_history) > 60: 
                            state.landmark_history.pop(0)
                        
                        # Check every 5 frames to save CPU
                        if len(state.landmark_history) >= 20 and len(state.landmark_history) % 5 == 0:
                            # COPY data to run DTW *outside* of lock to prevent freezing UI
                            history_copy = list(state.landmark_history)
                            
                            # Release main lock temporarily for heavy calc
                            state.lock.release()
                            try:
                                dynamic_match = state.engine.find_dynamic_gesture(history_copy)
                            finally:
                                state.lock.acquire() # Re-acquire immediately
                                
                            if dynamic_match:
                                logger.info(f"Dynamic Gesture Detected: {dynamic_match}")
                                state.current_gesture = dynamic_match 
                                state.landmark_history = []

                    if state.current_gesture:
                        # Continuous Action Check
                        if state.action_map.is_continuous(state.current_gesture):
                            # Continuous gestures should execute asynchronously to prevent locking the camera loop!
                            g_cont = state.current_gesture
                            lm_cont = state.latest_landmarks
                            def execute_cont(g=g_cont, lm=lm_cont):
                                try:
                                    state.action_map.execute(g, landmarks=lm)
                                except Exception as e:
                                    logger.error(f"Action execution error (Continuous): {e}")
                            
                            # Prevent memory leak/queue bloat by capping continuous action buffering
                            if len(state.action_queue) < 3: # Smaller queue for continuous to keep it fresh
                                state.action_queue.append({'func': execute_cont})
                            
                            state.last_action_name = "Tracking" 
                            state.last_continuous_action_time = time.time() # Use dedicated timestamp
                        else:
                            # One-Shot
                            if time.time() - state.last_action_time > state.cooldown:
                                # Check if action is continuous (scrolling, volume, etc)
                                is_cont = state.action_map.is_continuous(state.current_gesture)
                                
                                # Single Trigger Logic: Only trigger if different from last OR if continuous
                                if state.current_gesture != state.last_triggered_gesture or is_cont:
                                    logger.info(f"Triggering: {state.current_gesture} (Cont: {is_cont})")
                                    # Use Action Queue for zero-latency
                                    # FIX: Deep-bind variables to prevent C++ memory pointers from segfaulting later
                                    g_val = state.current_gesture
                                    lm_val = state.latest_landmarks
                                    def execute_and_log(g=g_val, lm=lm_val):
                                        try:
                                            action = state.action_map.execute(g, lm)
                                            if action:
                                                logger.info(f"Action Executed: {action}")
                                                state.last_action_name = action
                                        except Exception as action_e:
                                            logger.error(f"CRITICAL FIX: Action worker crash: {action_e}")
                                    
                                    state.action_queue.append({'func': execute_and_log})
                                    state.last_action_time = time.time() # FIX: Update cooldown instantly to prevent multi-trigger
                                    
                                    # Pop-up logic removed because pywebview is bypassed.
                                    state.last_triggered_gesture = state.current_gesture
                                else:
                                    pass
                    else:
                        pass
        
                elif state.mode == "RECORD":
                    pass
                elif state.mode == "RECORD_SEQUENCE":
                    # In this mode, we just visualize. The actual recording start/stop is handled by API.
                    if getattr(state, 'is_recording_sequence', False):
                        if not hasattr(state, 'sequence_buffer'):
                             state.sequence_buffer = []
                        
                        # Only append if we have landmarks
                        if state.latest_landmarks:
                            state.sequence_buffer.append(state.latest_landmarks)
                            state.last_action_name = f"Recording... {len(state.sequence_buffer)} frames"
                        else:
                            state.last_action_name = f"Recording... (Hand Lost)"

                elif state.mode == "MOUSE":
                    state.action_map._action_smart_mouse(state.latest_landmarks)
                    state.last_action_name = "Virtual Mouse Active"
                
                elif state.mode == "ATTENDANCE":
                    # Use the common confirmed_gesture

                    if confirmed_gesture and confirmed_gesture != state.last_triggered_gesture:
                        student_name, msg = state.attendance_mgr.mark_attendance(confirmed_gesture)
                        if student_name:
                            state.last_action_name = f"PRESENT: {student_name}"
                            state.last_action_time = time.time()
                            logger.info(f"Attendance: {student_name} ({confirmed_gesture}) - {msg}")
                            
                            # Real-World: Trigger Notification
                            if student_name and "success" in msg.lower():
                                # Try to find roll number for the alert
                                try:
                                    students = state.attendance_mgr.get_students()
                                    roll = next((s[3] for s in students if s[1] == student_name), "N/A")
                                    state.notification_engine.send_attendance_alert(student_name, roll)
                                except Exception as e:
                                    logger.error(f"Failed to trigger notification: {e}")
                        else:
                            if "Memory debounce" not in str(msg):
                                state.last_action_name = "Unknown Fingerprint"
                    
                elif state.mode == "HOME":
                    candidate = state.engine.find_gesture(state.latest_landmarks)
                    # Instant feedback for IoT is key
                    if candidate and candidate != state.last_triggered_gesture:
                        state.last_action_name = f"HOME_{candidate.upper()}"
                        state.last_action_time = time.time()
                        state.last_triggered_gesture = candidate

                elif state.mode == "MEDICAL":
                    # sterile gesture control for MRI/CT Viewers
                    try:
                        landmarks = state.latest_landmarks
                        if not landmarks: continue
                        
                        # --- 1. Pinch for ZOOM (Index + Thumb) ---
                        index_tip = landmarks[8]
                        thumb_tip = landmarks[4]
                        
                        # Calculate Euclidean distance
                        dist = np.sqrt((index_tip.x - thumb_tip.x)**2 + (index_tip.y - thumb_tip.y)**2)
                        
                        # Calibration: < 0.05 is pinch, > 0.1 is open
                        if dist < 0.05:
                            # Pinching - Zoom In
                            state.last_action_name = "MEDICAL_ZOOM_IN"
                            state.last_action_time = time.time()
                        elif dist > 0.2:
                            # Wide Open - Zoom Reset / Out
                             state.last_action_name = "MEDICAL_ZOOM_OUT"
                             state.last_action_time = time.time()
                        
                        # --- 2. Swipe for SLICE Navigation (Hand Position) ---
                        # Use wrist X position
                        wrist = landmarks[0]
                        if wrist.x < 0.2:
                            state.last_action_name = "MEDICAL_PREV_SLICE"
                            state.last_action_time = time.time()
                        elif wrist.x > 0.8:
                            state.last_action_name = "MEDICAL_NEXT_SLICE"
                            state.last_action_time = time.time()
                            
                    except Exception as e:
                        pass
                
                elif state.mode == "DRIVE":
                    # Automotive specific logic: Broad Gestures for Infotainment
                    candidate = state.engine.find_gesture(state.latest_landmarks)
                    
                    # Broad Motion Detection: Use Swipe Logic for Safety
                    gesture_action = None
                    
                    try:
                        # Simple wrist movement
                        wrist = state.latest_landmarks[0]
                        if wrist.x < 0.2:
                            gesture_action = "DRIVE_PREV_TRACK"
                        elif wrist.x > 0.8:
                            gesture_action = "DRIVE_NEXT_TRACK"
                        elif candidate == "open_palm":
                             gesture_action = "DRIVE_PLAY_PAUSE"
                    except: pass

                    if gesture_action and gesture_action != state.last_triggered_gesture:
                        # Drive mode triggers Voice Feedback
                        state.last_action_name = gesture_action
                        state.last_action_time = time.time()
                        state.last_triggered_gesture = gesture_action
                        
                        # Trigger Voice Announcement (Safe Driving)
                        speech_text = gesture_action.replace("DRIVE_", "").replace("_", " ").title()
                        def speak_action():
                            state.action_map.voice_engine.speak(f"{speech_text}")
                        state.action_queue.append({'func': speak_action})

                elif state.mode == "PRESENTATION":
                    # strictly force presentation behaviors for industry standardization
                    gesture_cmd = None
                    
                    if confirmed_gesture:
                        # 1. Try Personalized Mapping for Presentation Mode
                        # We use get_app_specific_action to check if a mode-specific override exists
                        action = state.action_map.get_app_specific_action(confirmed_gesture, "_PRESENTATION_MODE_")
                        if action:
                            def execute_personalized():
                                state.action_map.perform_action(action)
                            state.action_queue.append({'func': execute_personalized})
                            gesture_cmd = action
                        
                        # 2. Fallback to Defaults if no personalized action exists for this mode
                        if not gesture_cmd:
                            if confirmed_gesture == "open_palm":
                                gesture_cmd = "ppt_start"
                            elif confirmed_gesture == "closed_fist":
                                gesture_cmd = "ppt_stop"
                            elif confirmed_gesture == "thumb_up":
                                gesture_cmd = "ppt_next"
                            elif confirmed_gesture == "thumb_down":
                                gesture_cmd = "ppt_prev"
                            elif confirmed_gesture == "pointing_up":
                                gesture_cmd = "ppt_laser_pointer"
                            elif confirmed_gesture == "victory" or confirmed_gesture == "peace":
                                gesture_cmd = "ppt_pen"
                            elif confirmed_gesture == "iloveyou":
                                gesture_cmd = "ppt_white_screen"
                            
                            if gesture_cmd:
                                def do_ppt():
                                    state.action_map.perform_action(gesture_cmd)
                                state.action_queue.append({'func': do_ppt})

                    # Fallback dynamic swipes if gesture isn't static
                    if not gesture_cmd and state.latest_landmarks:
                        wrist = state.latest_landmarks[0]
                        if wrist.x < 0.2:
                            gesture_cmd = "ppt_prev"
                        elif wrist.x > 0.8:
                            gesture_cmd = "ppt_next"

                    if gesture_cmd and gesture_cmd != state.last_triggered_gesture:
                        state.last_action_name = f"SLIDE: {str(gesture_cmd).upper().replace('PPT_', '')}"
                        state.last_action_time = time.time()
                        state.last_triggered_gesture = gesture_cmd

                        # Execute the dynamic swipe action
                        if not confirmed_gesture: # It was a dynamic swipe
                            def do_swipe():
                                state.action_map.perform_action(gesture_cmd)
                            state.action_queue.append({'func': do_swipe})

                elif state.mode == "IDLE":
                    state.last_action_name = "Paused"
            else:
                state.current_gesture = None
                state.last_triggered_gesture = None 
                pending_gesture = None
                stability_count = 0
                # Reset history if hand lost? Maybe not, could be momentary occlusion.
                # But for dynamic gestures, a break usually means reset.
                if hasattr(state, 'landmark_history'):
                    state.landmark_history = []

            # Clear status text
            if time.time() - state.last_action_time > 3.0:
                if state.mode != "MOUSE":
                    state.last_action_name = ""
            
            # --- Training Metrics ---
            if state.latest_landmarks:
                state.training_metrics["brightness"] = int(cv2.mean(frame)[0])
                
                pts = state.latest_landmarks
                x_coords = [p.x for p in pts]
                y_coords = [p.y for p in pts]
                size = (max(x_coords) - min(x_coords)) * (max(y_coords) - min(y_coords))
                state.training_metrics["size"] = size
                
                if size < state.training_metrics["size_range"][0]: state.training_metrics["size_range"][0] = size
                if size > state.training_metrics["size_range"][1]: state.training_metrics["size_range"][1] = size
                
                p0 = pts[0]
                p9 = pts[9]
                import math
                angle = math.degrees(math.atan2(p9.y - p0.y, p9.x - p0.x))
                state.training_metrics["angle"] = angle
                
                if angle < state.training_metrics["angle_range"][0]: state.training_metrics["angle_range"][0] = angle
                if angle > state.training_metrics["angle_range"][1]: state.training_metrics["angle_range"][1] = angle
            else:
                state.training_metrics["brightness"] = int(cv2.mean(frame)[0])

            state.stability_score = stability_count
            
        # Compression & Output
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 75] 
        success, buffer = cv2.imencode('.jpg', frame, encode_param)
        if success:
            with state.lock:
                state.latest_frame_jpg = buffer.tobytes()
        
        # FPS Calculation & CPU Capping
        loop_end = time.time()
        dt = loop_end - loop_start
        
        target_delay = (1.0 / Config.FPS) - dt
        if target_delay > 0:
            time.sleep(target_delay)
            loop_end = time.time()
            dt = loop_end - loop_start
            
        if dt > 0:
            with state.lock:
                state.fps = int(1.0 / dt)
        loop_start = loop_end

# --- Flask Routes ---
@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/float')
def float_view():
    return app.send_static_file('float.html')

@app.route('/attendance')
def attendance_view():
    return app.send_static_file('attendance.html')

@app.route('/admin')
def admin_view():
    return app.send_static_file('admin.html')

@app.route('/hub')
def hub_view():
    return app.send_static_file('hub.html')

@app.route('/presentation')
def presentation_view():
    return app.send_static_file('presentation.html')

@app.route('/medical')
def medical_view():
    return app.send_static_file('medical.html')

@app.route('/home')
def home_view():
    return app.send_static_file('home.html')

@app.route('/drive')
def drive_view():
    return app.send_static_file('drive.html')

@app.route('/security')
def security_view():
    return app.send_static_file('security.html')

@app.route('/video_feed')
def video_feed():
    def generate():
        while True:
            with state.lock:
                frame = state.latest_frame_jpg
            
            if frame:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            time.sleep(1.0 / Config.FPS)
            
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/status', methods=['GET'])
def get_status():
    with state.lock:
        return jsonify({
            "mode": state.mode,
            "detected_gesture": state.current_gesture,
            "last_action": state.last_action_name,
            "is_hand_visible": state.latest_landmarks is not None,
            "fps": state.fps,
            "stability_score": state.stability_score,
            "theme": state.theme,
            "domain": state.domain,
            "training_metrics": state.training_metrics,
            "camera_config": state.camera_config,
            "voice_auto_active": state.action_map.voice_engine.auto_mode_active,
            "floating_camera_active": state.floating_camera_active
        })

@app.route('/api/mode', methods=['POST'])
def set_mode():
    data = request.json
    new_mode = data.get("mode")
    if new_mode in ["DETECT", "RECORD", "RECORD_SEQUENCE", "MOUSE", "ATTENDANCE", "IDLE"]:
        with state.lock:
            state.mode = new_mode
            if new_mode == "RECORD":
                state.training_metrics["size_range"] = [1.0, 0.0]
                state.training_metrics["angle_range"] = [180.0, -180.0]
            logger.info(f"Mode switched to {new_mode}")
        return jsonify({"status": "success", "mode": state.mode})
    return jsonify({"error": "Invalid mode"}), 400

@app.route('/api/sequence/start', methods=['POST'])
def start_sequence_recording():
    with state.lock:
        state.mode = "RECORD_SEQUENCE"
        state.is_recording_sequence = True
        state.sequence_buffer = []
        logger.info("Started Sequence Recording")
    return jsonify({"status": "success"})

@app.route('/api/sequence/stop', methods=['POST'])
def stop_sequence_recording():
    try:
        data = request.json
        raw_name = data.get("name")
        
        # Sanitize name
        import re
        name = re.sub(r'[<>:"/\\|?*]', '', raw_name) if raw_name else None
        
        with state.lock:
            state.is_recording_sequence = False
            buffer = getattr(state, 'sequence_buffer', [])
            
            if not name:
                 return jsonify({"error": "Invalid Name"}), 400
                 
            if len(buffer) < 10:
                 return jsonify({"error": f"Sequence too short ({len(buffer)} frames). Was the hand detected?"}), 400
                 
        # Release lock before heavy save operation
        if state.engine.save_sequence(name, buffer):
            logger.info(f"Saved sequence {name} with {len(buffer)} frames")
            return jsonify({"status": "success", "frames": len(buffer)})
        else:
            return jsonify({"error": "Failed to save sequence (Engine Error)"}), 500
    except Exception as e:
        logger.error(f"Sequence save exception: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/api/theme', methods=['POST'])
def set_theme():
    data = request.json
    new_theme = data.get("theme")
    if new_theme:
        with state.lock:
            state.theme = new_theme
        logger.info(f"Theme set to {new_theme}")
    return jsonify({"error": "Invalid theme"}), 400

@app.route('/api/settings', methods=['POST'])
def update_settings():
    data = request.json
    width = data.get("width")
    height = data.get("height")
    fps = data.get("fps")
    
    if width and height and fps:
        with state.lock:
            state.camera_config = {"width": width, "height": height, "fps": fps}
            state.camera_needs_update = True
        return jsonify({"status": "success"})
    return jsonify({"error": "Missing parameters"}), 400

@app.route('/api/gestures', methods=['GET'])
def get_gestures():
    result = []
    # 1. Static Gestures via Engine
    for name in state.engine.gestures.keys():
        try:
            sample_dir = os.path.join("samples", name)
            if os.path.exists(sample_dir):
                files = [f for f in os.listdir(sample_dir) if f.lower().endswith('.jpg')]
                count = len(files)
            else:
                count = 0
        except:
            count = 0
        result.append({"name": name, "samples": count, "type": "static"})

    # 2. Dynamic Sequences
    if hasattr(state.engine, 'sequences'):
        for name, seq_data in state.engine.sequences.items():
            # For sequences, 'samples' is just 1 (the sequence itself) or number of frames?
            # Let's show frame count as samples for now
            result.append({"name": name, "samples": len(seq_data), "type": "dynamic"})

    return jsonify(result)

@app.route('/api/training/stats')
def training_stats():
    return jsonify(state.engine.get_training_stats())

@app.route('/api/gestures', methods=['GET', 'POST'])
def save_gesture_sample():
    data = request.json
    name = data.get("name")
    
    if not name:
        return jsonify({"error": "Name required"}), 400
        
    with state.lock:
        landmarks = state.latest_landmarks
        frame_jpg = state.latest_frame_jpg
        
    if landmarks:
        if state.engine.save_gesture(name, landmarks):
            if frame_jpg:
                try:
                    sample_dir = os.path.join("samples", name)
                    os.makedirs(sample_dir, exist_ok=True)
                    timestamp = int(time.time() * 1000)
                    filepath = os.path.join(sample_dir, f"{timestamp}.jpg")
                    with open(filepath, "wb") as f:
                        f.write(frame_jpg)
                    logger.info(f"Saved image sample to {filepath}")
                except Exception as e:
                    logger.error(f"Failed to save image sample: {e}")

            return jsonify({"status": "success", "message": f"Sample added to {name}"})
        else:
            return jsonify({"error": "Failed to save sample"}), 500
    else:
        return jsonify({"error": "No hand detected"}), 404

@app.route('/api/gestures/<name>/images', methods=['GET'])
def get_gesture_images(name):
    try:
        # Check for filter parameter. Default to 'original'
        # mode='all' will be used by Dataset Dashboard
        mode = request.args.get('type', 'original') 
        
        sample_dir = os.path.join("samples", name)
        if not os.path.exists(sample_dir):
            return jsonify([])
        
        files = sorted(os.listdir(sample_dir), reverse=True) 
        images = [f for f in files if f.endswith('.jpg')]
        
        # Filter logic
        if mode == 'original':
            # Exclude files with '_aug_' in the name
            images = [f for f in images if "_aug_" not in f]
            images = images[:50] # Limit for gallery performance
        elif mode == 'all':
            images = images[:500] # Limit specifically for dataset view to avoid crashing browser
        
        urls = [f"/samples/{quote(name)}/{img}" for img in images]
        return jsonify(urls)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/gestures/<name>/samples/<path:filename>', methods=['DELETE'])
def delete_sample(name, filename):
    try:
        sample_dir = os.path.join("samples", name)
        filepath = os.path.join(sample_dir, filename)
        
        if not os.path.exists(filepath):
            return jsonify({"error": "File not found"}), 404
        
        all_files = sorted([f for f in os.listdir(sample_dir) if f.endswith('.jpg')])
        
        if filename in all_files:
            # Only try to update engine if it's an original (not augmented)
            # Augmented images aren't in the engine memory usually unless reloaded
            # But just deleting file is safe
            os.remove(filepath)
            
            # Try to remove from engine if possible (best effort)
            try:
                index = all_files.index(filename)
                state.engine.delete_sample(name, index)
            except:
                pass 
                
            return jsonify({"status": "success"})
        else:
             return jsonify({"error": "File sync error"}), 500

    except Exception as e:
        logger.error(f"Sample delete error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/gestures/<name>/samples/<path:filename>/augment', methods=['GET'])
def augment_sample_preview(name, filename):
    try:
        sample_dir = os.path.join("samples", name)
        filepath = os.path.join(sample_dir, filename)
        
        if not os.path.exists(filepath):
            return jsonify({"error": "File not found"}), 404

        img = cv2.imread(filepath)
        if img is None:
            return jsonify({"error": "Failed to read image"}), 500

        augmented = augment_image(img, fast=True)
        ret, buffer = cv2.imencode('.jpg', augmented)
        if not ret:
            return jsonify({"error": "Failed to encode image"}), 500
            
        import base64
        encoded = base64.b64encode(buffer).decode('utf-8')
        return jsonify({"augmented_image": f"data:image/jpeg;base64,{encoded}"})

    except Exception as e:
        logger.error(f"Augmentation error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/gestures/<name>/samples/<path:filename>/bulk_augment', methods=['GET'])
def bulk_augment_sample_preview(name, filename):
    try:
        sample_dir = os.path.join("samples", name)
        filepath = os.path.join(sample_dir, filename)
        
        if not os.path.exists(filepath):
            return jsonify({"error": "File not found"}), 404

        img = cv2.imread(filepath)
        if img is None:
            return jsonify({"error": "Failed to read image"}), 500

        count = request.args.get('count', 100, type=int)
        augmented_list = generate_bulk_augmentations(img, count=count)
        
        results = []
        import base64
        for aug in augmented_list:
            ret, buffer = cv2.imencode('.jpg', aug)
            if ret:
                encoded = base64.b64encode(buffer).decode('utf-8')
                results.append(f"data:image/jpeg;base64,{encoded}")
        
        return jsonify({"augmented_images": results})

    except Exception as e:
        logger.error(f"Bulk augmentation error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/gestures/<name>/samples/<path:filename>/augment_raw', methods=['GET'])
def augment_sample_raw(name, filename):
    try:
        sample_dir = os.path.join("samples", name)
        filepath = os.path.join(sample_dir, filename)
        
        if not os.path.exists(filepath):
            return "File not found", 404

        img = cv2.imread(filepath)
        if img is None:
            return "Failed to read image", 500

        seed = request.args.get('seed', type=int)
        thumb_w = request.args.get('w', type=int)
        
        # Safe seed modulo
        if seed:
            seed = seed % (2**32 - 1)

        augmented = augment_image(img, thumb_w=thumb_w, seed=seed, fast=True)
        quality = 80
        ret, buffer = cv2.imencode('.jpg', augmented, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if not ret:
            return "Failed to encode image", 500
            
        return Response(buffer.tobytes(), mimetype='image/jpeg', headers={
            'Cache-Control': 'public, max-age=3600'
        })
    except Exception as e:
        logger.error(f"Raw augmentation error: {e}")
        return str(e), 500

@app.route('/api/gestures/<name>/samples/<path:filename>/sprite', methods=['GET'])
def augment_sample_sprite(name, filename):
    try:
        sample_dir = os.path.join("samples", name)
        filepath = os.path.join(sample_dir, filename)
        
        if not os.path.exists(filepath):
            return "File not found", 404

        img = cv2.imread(filepath)
        if img is None:
            return "Failed to read image", 500

        count = request.args.get('count', 100, type=int)
        count = min(400, max(1, count))
        
        sprite = generate_augmentation_sprite(img, count=count)
        ret, buffer = cv2.imencode('.jpg', sprite, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if not ret:
            return "Failed to encode image", 500
            
        return Response(buffer.tobytes(), mimetype='image/jpeg')
    except Exception as e:
        logger.error(f"Sprite augmentation error: {e}")
        return str(e), 500

@app.route('/api/gestures/<name>/samples/<path:filename>/save_augment', methods=['POST'])
def save_bulk_augment(name, filename):
    try:
        data = request.json
        count = data.get('count', 10)
        
        sample_dir = os.path.join("samples", name)
        filepath = os.path.join(sample_dir, filename)
        
        if not os.path.exists(filepath):
            return jsonify({"error": "Source file not found"}), 404

        img = cv2.imread(filepath)
        if img is None:
            return jsonify({"error": "Failed to read image"}), 500
            
        # Generate using deterministic seeds
        from augmentation_utils import augment_image
        augmented_list = [augment_image(img, seed=i % (2**32 - 1)) for i in range(count)]
        
        saved_count = 0
        base_timestamp = int(time.time() * 1000)
        
        for i, aug_img in enumerate(augmented_list):
            save_name = f"{base_timestamp}_aug_{i}.jpg"
            save_path = os.path.join(sample_dir, save_name)
            cv2.imwrite(save_path, aug_img)
            saved_count += 1
            
        return jsonify({"status": "success", "saved": saved_count})
        
    except Exception as e:
        logger.error(f"Save bulk error: {e}")
        return jsonify({"error": str(e)}), 500

# --- STREAMING AUGMENTATION ENDPOINT ---
@app.route('/api/gestures/<name>/augment_all', methods=['POST'])
def augment_all_samples(name):
    data = request.json
    count_per_sample = data.get('count', 3) 
    
    sample_dir = os.path.join("samples", name)
    if not os.path.exists(sample_dir):
        return jsonify({"error": "Gesture directory not found"}), 404
        
    # 1. Identify "Original" samples (exclude previous augmentations)
    all_files = sorted([f for f in os.listdir(sample_dir) if f.lower().endswith('.jpg')])
    originals = [f for f in all_files if "_aug_" not in f]
    
    if not originals:
        return jsonify({"error": "No original samples found to augment"}), 404
        
    from augmentation_utils import augment_image
    
    def generate():
        total_to_generate = len(originals) * count_per_sample
        generated_count = 0
        base_timestamp = int(time.time() * 1000)
        
        # Initial status
        yield json.dumps({"status": "start", "total": total_to_generate, "current": 0}) + "\n"
        
        for idx, filename in enumerate(originals):
            filepath = os.path.join(sample_dir, filename)
            img = cv2.imread(filepath)
            
            if img is None: 
                continue
                
            for i in range(count_per_sample):
                # FIX: Ensure seed is within 32-bit integer range
                seed = (base_timestamp + idx + (i * 9999)) % (2**32 - 1)
                
                aug_img = augment_image(img, seed=seed)
                
                save_name = f"{base_timestamp}_src_{idx}_aug_{i}.jpg"
                save_path = os.path.join(sample_dir, save_name)
                cv2.imwrite(save_path, aug_img)
                
                generated_count += 1
                
                # Yield progress update
                yield json.dumps({"status": "progress", "total": total_to_generate, "current": generated_count}) + "\n"
                     
        # Final message
        yield json.dumps({"status": "complete", "total": total_to_generate, "current": generated_count}) + "\n"

    return Response(stream_with_context(generate()), mimetype='application/x-ndjson')

@app.route('/api/gestures/<name>', methods=['DELETE'])
def delete_gesture(name):
    try:
        if state.engine.delete_gesture(name):
            return jsonify({"status": "success"})
        else:
            return jsonify({"error": "Gesture not found"}), 404
    except Exception as e:
        logger.error(f"Gesture delete error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/gestures/<name>/rename', methods=['POST'])
def rename_gesture(name):
    data = request.json
    new_name = data.get("new_name")
    
    if not new_name:
        return jsonify({"error": "New name required"}), 400
        
    if new_name == name:
        return jsonify({"status": "success", "message": "No change"})

    try:
        with state.lock:
            if state.engine.rename_gesture(name, new_name):
                state.action_map.rename_mapping(name, new_name)
                return jsonify({"status": "success"})
            else:
                return jsonify({"error": "Rename failed (Name exists or invalid)"}), 400
    except Exception as e:
        logger.error(f"Gesture rename error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/samples/<path:filename>')
def serve_sample(filename):
    return send_from_directory('samples', filename, max_age=31536000)

@app.route('/api/actions', methods=['GET'])
def get_actions():
    return jsonify(state.action_map.get_available_actions())

@app.route('/api/map', methods=['GET'])
def get_mapping():
    return jsonify(state.action_map.mapping)

@app.route('/api/map', methods=['POST'])
def map_gesture():
    data = request.json
    gesture = data.get("gesture")
    action = data.get("action")
    app_name = data.get("app") # Optional app name
    # Allow empty string for action to reset to default
    if gesture is not None and action is not None:
        state.action_map.map_gesture(gesture, action, app_name)
        if app_name:
            logger.info(f"Mapped {gesture} -> '{action}' for {app_name}")
        else:
            logger.info(f"Mapped {gesture} -> '{action}'")
        return jsonify({"status": "success"})
    return jsonify({"error": "Invalid data"}), 400

@app.route('/api/map/bulk', methods=['POST'])
def map_gestures_bulk():
    data = request.json
    app_name = data.get("app")
    mappings = data.get("mappings") # Expected as {gesture: action, ...}
    
    logger.info(f"Received bulk map request: app={app_name}, mappings type={type(mappings)}")
    if app_name and isinstance(mappings, dict):
        result = state.action_map.map_gestures_bulk(app_name, mappings)
        logger.info(f"map_gestures_bulk result: {result}")
        if result:
            logger.info(f"Bulk mapped {len(mappings)} gestures for {app_name}")
            return jsonify({"status": "success"})
        else:
            logger.error("action_map.map_gestures_bulk returned False")
            return jsonify({"error": "Failed to save mappings"}), 500
    
    logger.error(f"Invalid data. app_name={app_name}, mappings={mappings}")
    return jsonify({"error": "Invalid data"}), 400

@app.route('/api/active_app', methods=['GET'])
def get_active_app():
    app_name = state.action_map.get_active_app()
    return jsonify({"app": app_name})

@app.route('/api/running_apps', methods=['GET'])
def get_running_apps():
    apps = state.action_map.get_running_apps()
    return jsonify({"apps": apps})

@app.route('/api/map/app', methods=['GET'])
def get_app_mappings():
    app_name = request.args.get("app")
    if not app_name:
        return jsonify(state.action_map.mapping_data.get("profiles", {}).get("default", {}).get("apps", {}))
    
    app_mapping = state.action_map.mapping_data.get("profiles", {}).get("default", {}).get("apps", {}).get(app_name, {})
    return jsonify(app_mapping)

@app.route('/api/exec', methods=['POST'])
def exec_action():
    data = request.json
    action = data.get("action")
    if action:
        result = state.action_map.perform_action(action)
        return jsonify({"status": "success", "result": result})
    return jsonify({"error": "No action provided"}), 400

@app.route('/api/split-pdf', methods=['POST'])
def process_split_pdf():
    if 'pdf' not in request.files:
        return jsonify({"error": "No PDF file uploaded"}), 400
    
    file = request.files['pdf']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    try:
        start_page = int(request.form.get('start_page', 1))
        end_page = int(request.form.get('end_page', 1))
        
        if file and file.filename.endswith('.pdf'):
            filename = secure_filename(file.filename)
            temp_path = os.path.join("temp_uploads", filename)
            os.makedirs("temp_uploads", exist_ok=True)
            file.save(temp_path)
            
            reader = PdfReader(temp_path)
            writer = PdfWriter()
            total_pages = len(reader.pages)
            
            if start_page < 1 or end_page > total_pages or start_page > end_page:
                return jsonify({"error": f"Invalid page range (1-{total_pages})"}), 400
            
            for i in range(start_page - 1, end_page):
                writer.add_page(reader.pages[i])
            
            output_filename = f"{os.path.splitext(filename)[0]}_split_{start_page}_to_{end_page}.pdf"
            output_path = os.path.join(os.path.expanduser("~"), "Downloads", output_filename)
            
            counter = 1
            base_output = os.path.splitext(output_path)[0]
            while os.path.exists(output_path):
                output_path = f"{base_output}_{counter}.pdf"
                counter += 1
                
            with open(output_path, "wb") as f:
                writer.write(f)
            
            os.remove(temp_path)
            return jsonify({
                "status": "success", 
                "message": f"Split complete! Saved to Downloads as {os.path.basename(output_path)}"
            })
    except Exception as e:
        logger.error(f"Error splitting PDF: {e}")
        return jsonify({"error": str(e)}), 500
    return jsonify({"error": "Unknown error"}), 500

# --- Attendance API ---
    return jsonify(result)

@app.route('/api/attendance/export', methods=['GET'])
def export_attendance_logs():
    try:
        logs = state.attendance_mgr.get_logs(limit=1000)
        import csv
        import io
        from flask import make_response

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['ID', 'Student Name', 'Roll Number', 'Timestamp', 'Status'])
        
        for log in logs:
            writer.writerow(log)
            
        response = make_response(output.getvalue())
        response.headers["Content-Disposition"] = f"attachment; filename=attendance_report_{int(time.time())}.csv"
        response.headers["Content-type"] = "text/csv"
        return response
    except Exception as e:
        logger.error(f"Export error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/attendance/students', methods=['GET'])
def get_students_list():
    students = state.attendance_mgr.get_students()
    result = []
    for s in students:
        result.append({
            "id": s[0],
            "name": s[1],
            "gesture_name": s[2],
            "roll_number": s[3]
        })
    return jsonify(result)

@app.route('/api/attendance/register', methods=['POST'])
def register_student():
    data = request.json
    name = data.get("name")
    gesture_name = data.get("gesture_name")
    roll_number = data.get("roll_number")
    
    if not name or not gesture_name:
        return jsonify({"error": "Name and Gesture Name are required"}), 400
        
    success, msg = state.attendance_mgr.register_student(name, gesture_name, roll_number)
    if success:
        return jsonify({"status": "success", "message": msg})
    else:
        return jsonify({"error": msg}), 400

@app.route('/api/attendance/students/<int:student_id>', methods=['DELETE'])
def delete_student(student_id):
    try:
        with sqlite3.connect(state.attendance_mgr.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM attendance WHERE student_id = ?", (student_id,))
            cursor.execute("DELETE FROM students WHERE id = ?", (student_id,))
            conn.commit()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- Enterprise Hub API ---
@app.route('/api/hub/domain', methods=['POST'])
def set_domain():
    data = request.json
    domain = data.get("domain")
    if domain:
        with state.lock:
            state.domain = domain
            # Sync mode with domain
            if domain == "INDUSTRIAL":
                state.mode = "ATTENDANCE"
            elif domain == "HOME":
                state.mode = "HOME"
            elif domain == "AUTOMOTIVE":
                state.mode = "DRIVE"
            elif domain == "MEDICAL":
                state.mode = "MEDICAL" 
            elif domain == "PRESENTATION":
                state.mode = "PRESENTATION"
            else:
                state.mode = "DETECT"
        logger.info(f"Domain switched to {domain}, Mode synced to {state.mode}")
        return jsonify({"status": "success", "domain": domain, "mode": state.mode})
    return jsonify({"error": "Invalid domain"}), 400

@app.route('/api/webhook/trigger', methods=['POST'])
def webhook_proxy():
    """Proxy for triggering external IoT devices."""
    data = request.json
    target_url = data.get("url")
    payload = data.get("payload", {})
    
    if not target_url:
        return jsonify({"error": "URL required"}), 400
        
    try:
        import requests
        # Run in background to not block camera loop
        def do_request():
            try:
                requests.post(target_url, json=payload, timeout=2)
                logger.info(f"Webhook triggered: {target_url}")
            except: pass
            
        threading.Thread(target=do_request, daemon=True).start()
        return jsonify({"status": "sent"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/voice/toggle', methods=['POST'])
def toggle_voice_auto():
    data = request.json
    enabled = data.get("enabled", False)
    engine = state.action_map.voice_engine
    if enabled:
        engine.start_auto_mode()
    else:
        engine.stop_auto_mode()
    return jsonify({"status": "success", "enabled": engine.auto_mode_active})

if __name__ == '__main__':
    print("This file is part of the Desktop Application and cannot be run directly.")
    print("Please use 'start_app.bat' to launch the application.")
    import sys
    sys.exit(1)