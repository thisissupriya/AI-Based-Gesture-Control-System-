import cv2
import numpy as np

# Colors (B, G, R)
COLOR_BG = (20, 20, 20)           # Dark Gray
COLOR_PRIMARY = (0, 255, 217)     # Cyan/Neon Blue
COLOR_SECONDARY = (255, 0, 128)   # Neon Purple
COLOR_TEXT = (255, 255, 255)      # White
COLOR_ACCENT = (0, 128, 255)      # Orange/Gold

HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (0, 9), (9, 10), (10, 11), (11, 12),
    (0, 13), (13, 14), (14, 15), (15, 16),
    (0, 17), (17, 18), (18, 19), (19, 20),
    (5, 9), (9, 13), (13, 17)
]

def draw_styled_landmarks(image, detection_result=None, theme="DEFAULT", manual_landmarks=None):
    hand_landmarks_list = manual_landmarks if manual_landmarks else (detection_result.hand_landmarks if detection_result else [])
    if not hand_landmarks_list:
        return image
        
    # --- Theme Config (BGR) ---
    if theme == "CYBERPUNK":
        # Pink & Cyan
        col_line = (255, 0, 255)    # Magenta
        col_joint = (255, 255, 0)   # Cyan
        col_core = (255, 255, 255)  # White
        thickness = 2
    elif theme == "MATRIX":
        # Matrix Green
        col_line = (0, 150, 0)      # Dark Green
        col_joint = (0, 255, 0)     # Bright Green
        col_core = (0, 50, 0)       # Blackish
        thickness = 1
    elif theme == "GOLD":
        # Gold & White
        col_line = (0, 215, 255)    # Gold
        col_joint = (255, 255, 255) # White
        col_core = (0, 165, 255)    # Orange
        thickness = 2
    else:
        # Default (GestureOS Cyan/Purple)
        col_line = (217, 255, 0)    # Cyan (BGR 0, 255, 217 -> 217, 255, 0?? No. Cyan is 0,255,255. App uses custom.)
        # Let's use existing:
        col_line = (217, 255, 0)    # Approx Cyan from top
        col_joint = (128, 0, 255)   # Purple
        col_core = (255, 255, 255)
        thickness = 2

    for hand_landmarks in hand_landmarks_list:
        h, w, c = image.shape
        
        # Draw Connections
        for connection in HAND_CONNECTIONS:
            start_idx = connection[0]
            end_idx = connection[1]
            p1 = hand_landmarks[start_idx]
            p2 = hand_landmarks[end_idx]
            x1, y1 = int(p1.x * w), int(p1.y * h)
            x2, y2 = int(p2.x * w), int(p2.y * h)
            
            cv2.line(image, (x1, y1), (x2, y2), col_line, thickness)
            
        # Draw Joints
        for landmark in hand_landmarks:
            x, y = int(landmark.x * w), int(landmark.y * h)
            # Outer glow
            cv2.circle(image, (x, y), 5, col_joint, -1)
            # Inner core
            cv2.circle(image, (x, y), 2, col_core, -1)
            
    return image

def draw_ui(image, mode, gesture_name, last_action, recording_data):
    """
    Draws a futuristic UI overlay with Glassmorphism and Neon accents.
    """
    h, w, c = image.shape
    
    # --- Config ---
    SIDEBAR_W = 280
    
    # 1. Glass Sidebar Overlay
    # Create a separate layer for the sidebar to apply blur/alpha
    overlay = image.copy()
    
    # Darken Sidebar area
    cv2.rectangle(overlay, (0, 0), (SIDEBAR_W, h), (10, 10, 15), -1)
    
    # Header bar background
    cv2.rectangle(overlay, (SIDEBAR_W, 0), (w, 60), (5, 5, 10), -1)
    
    # Blend Sidebar
    alpha_sidebar = 0.85
    cv2.addWeighted(overlay, alpha_sidebar, image, 1 - alpha_sidebar, 0, image)
    
    # 2. Border Separator (Neon)
    cv2.line(image, (SIDEBAR_W, 0), (SIDEBAR_W, h), COLOR_PRIMARY, 1)
    
    # 3. Branding
    font_title = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(image, "GESTURE", (20, 40), font_title, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(image, "OS", (160, 40), font_title, 0.8, COLOR_PRIMARY, 2, cv2.LINE_AA)
    
    # 4. Mode Logic
    y_start = 100
    
    # Mode Pill
    mode_color = COLOR_PRIMARY if mode == "DETECT" else COLOR_ACCENT
    cv2.rectangle(image, (20, y_start), (SIDEBAR_W - 20, y_start + 40), mode_color, -1)
    cv2.putText(image, f"MODE: {mode}", (35, y_start + 28), cv2.FONT_HERSHEY_DUPLEX, 0.7, (0,0,0), 1, cv2.LINE_AA)
    
    # 5. Dynamic Info Area
    y_info = y_start + 80
    
    # Recognized Gesture
    cv2.putText(image, "DETECTED GESTURE", (20, y_info), cv2.FONT_HERSHEY_PLAIN, 1.1, (150, 150, 150), 1, cv2.LINE_AA)
    
    # Show Pending if waiting, else show Current
    pending = recording_data.get('pending_gesture')
    progress = recording_data.get('stability_progress', 0.0)
    
    display_gesture = gesture_name if gesture_name else (pending if pending else "--")
    color_gesture = COLOR_TEXT
    
    if pending and not gesture_name:
        color_gesture = (255, 255, 100) # Yellowish for pending
        
    cv2.putText(image, display_gesture, (20, y_info + 35), cv2.FONT_HERSHEY_TRIPLEX, 1.2, color_gesture, 1, cv2.LINE_AA)
    
    # Stability Bar (if pending)
    if pending and progress > 0.1 and progress < 1.0:
        bar_w = SIDEBAR_W - 40
        bar_h = 4
        bar_x = 20
        bar_y = y_info + 50
        # Background
        cv2.rectangle(image, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h), (50,50,50), -1)
        # Fill
        fill_w = int(bar_w * progress)
        cv2.rectangle(image, (bar_x, bar_y), (bar_x + fill_w, bar_y + bar_h), COLOR_PRIMARY, -1)

    # Last Action
    y_action = y_info + 100
    cv2.putText(image, "LAST ACTION", (20, y_action), cv2.FONT_HERSHEY_PLAIN, 1.1, (150, 150, 150), 1, cv2.LINE_AA)
    
    action_text = last_action if last_action else "Ready"
    action_color = COLOR_ACCENT if last_action else (100, 100, 100)
    
    # Text wrap if too long
    if len(action_text) > 18:
        action_text = action_text[:16] + ".."
        
    cv2.putText(image, action_text, (20, y_action + 35), cv2.FONT_HERSHEY_DUPLEX, 0.9, action_color, 1, cv2.LINE_AA)
    
    # 6. Center HUD Items (Stability Ring)
    # Only draw this if we have a pending gesture but not yet confirmed
    if pending and not gesture_name and progress > 0:
        center_x, center_y = w // 2, h // 2
        radius = 80
        # Background Ring
        cv2.ellipse(image, (center_x, center_y), (radius, radius), 0, 0, 360, (50, 50, 50), 4, cv2.LINE_AA)
        # Progress Ring
        end_angle = int(360 * progress)
        cv2.ellipse(image, (center_x, center_y), (radius, radius), -90, 0, end_angle, COLOR_PRIMARY, 4, cv2.LINE_AA)
        # Text
        text_size = cv2.getTextSize(pending, cv2.FONT_HERSHEY_DUPLEX, 1, 2)[0]
        tx = center_x - text_size[0] // 2
        ty = center_y + text_size[1] // 2
        cv2.putText(image, pending, (tx, ty), cv2.FONT_HERSHEY_DUPLEX, 1, COLOR_TEXT, 2, cv2.LINE_AA)

    # 7. Bottom Instructions
    # Helper box
    box_h = 120
    cv2.rectangle(image, (0, h - box_h), (SIDEBAR_W, h), (20, 20, 25), -1)
    cv2.line(image, (0, h - box_h), (SIDEBAR_W, h - box_h), (80, 80, 80), 1)
    
    instr_font = cv2.FONT_HERSHEY_PLAIN
    instr_color = (180, 180, 180)
    start_y = h - box_h + 25
    
    if mode == "DETECT":
        lines = ["Commands:", "[R] Record Gesture", "[Q] Quit App"]
    elif mode == "SELECT_ACTION":
         lines = ["Select Action 0-9", "to map detected", "gesture."]
    elif mode == "RECORD":
        if recording_data.get('typing_mode'):
             lines = ["Type Name...", "[Enter] Confirm"]
        else:
            lines = ["[S] Sample Frame", "[D] Done/Detect", "[Q] Cancel"]

    for i, line in enumerate(lines):
        cv2.putText(image, line, (20, start_y + (i*25)), instr_font, 1.1, instr_color, 1, cv2.LINE_AA)

    # 8. Modals (Record / Select) - Keeping relatively simple but styled
    if mode == "RECORD" and recording_data.get('typing_mode'):
        # Dim background
        dim_overlay = image.copy()
        cv2.rectangle(dim_overlay, (0,0), (w,h), (0,0,0), -1)
        cv2.addWeighted(dim_overlay, 0.6, image, 0.4, 0, image)
        
        # Input Box
        cx, cy = w//2, h//2
        bw, bh = 400, 150
        cv2.rectangle(image, (cx-bw//2, cy-bh//2), (cx+bw//2, cy+bh//2), (30,30,35), -1)
        cv2.rectangle(image, (cx-bw//2, cy-bh//2), (cx+bw//2, cy+bh//2), COLOR_ACCENT, 2)
        
        cv2.putText(image, "NAME NEW GESTURE", (cx - 100, cy - 30), cv2.FONT_HERSHEY_DUPLEX, 0.8, (200,200,200), 1, cv2.LINE_AA)
        
        inp = recording_data['name_input'] + "|"
        cv2.putText(image, inp, (cx - 150, cy + 20), cv2.FONT_HERSHEY_TRIPLEX, 1.2, COLOR_PRIMARY, 1, cv2.LINE_AA)

    if mode == "SELECT_ACTION":
        # Sidebar Expansion for list
        # Overwrite standard sidebar bottom
        list_y = y_info + 160
        cv2.putText(image, "MAP TO ACTION:", (20, list_y), cv2.FONT_HERSHEY_PLAIN, 1.1, COLOR_SECONDARY, 1)
        
        actions = recording_data.get('available_actions', [])
        for i, act in enumerate(actions):
            if i > 5: break 
            act_name = act.replace("_", " ").title()
            cv2.putText(image, f"{i}: {act_name}", (20, list_y + 30 + (i*25)), cv2.FONT_HERSHEY_PLAIN, 1.0, COLOR_TEXT, 1)
        
        cv2.putText(image, "Press 0-9...", (20, h - 20), cv2.FONT_HERSHEY_PLAIN, 1.0, (100,100,100), 1)

    return image
