# Hand Gesture Control 🖐️💻

Control your Windows desktop entirely with hand gestures! This application uses AI (MediaPipe) to track your hand and trigger custom actions like volume control, virtual mouse, refreshing pages, and taking screenshots.

![Hand Gesture Control UI](https://via.placeholder.com/800x450?text=Hand+Gesture+Control+Preview)

## ✨ Features

- **Virtual Mouse**: Move cursor, click, and drag using your hand.
- **Custom Gestures**: Train your own gestures (e.g., "Peace Sign", "Fist", "Open Palm") and map them to ANY key or shortcut.
- **Floating Camera**: "Always on Top" floating window to see your hand status while using other apps.
- **Premium UI**: Beautiful Glassmorphism dark mode design.
- **Pop-up Feedback**: Main window automatically restores when an action is triggered.
- **Privacy First**: All processing happens locally on your machine.

---

## 🛠️ Installation & Setup

### Prerequisites
1. **Python 3.8** or higher installed on your system.
2. A working **Webcam**.
3. **Windows 10/11** (for best desktop automation support).

### Step 1: Clone or Download
Clone this repository or download the ZIP file and extract it.
```bash
git clone https://github.com/Aman130901/-hand-gesture-control.git
cd -hand-gesture-control
```

### Step 2: Install Dependencies
Open a terminal (Command Prompt or PowerShell) in the project folder and run:
```bash
pip install -r requirements.txt
```
*Note: If you encounter permission errors, try running as Administrator.*

**Dependencies included:**
- `opencv-python` (Computer Vision)
- `mediapipe` (Hand Tracking)
- `pyautogui` (Desktop Automation)
- `flask` & `flask-cors` (Backend Server)
- `pywebview` (Desktop App Wrapper)

---

## 🚀 How to Run

### Method 1: The Easy Way (Recommended)
Double-click the **`start_desktop.bat`** file in the project folder. 
This will automatically launch the backend server and the desktop application window.

### Method 2: Manual Start
Open your terminal in the project directory and run:
```bash
python desktop_app.py
```

---

## 🎮 How to Use

1. **Detection Mode**: The app starts in detection mode.
   - **Point**: Move the mouse cursor.
   - **Pinch (Index+Thumb)**: Left Click / Drag.
   - **Pinch (Middle+Thumb)**: Right Click.
2. **Gesture Mapping**:
   - Go to the **Train** tab to record new gestures.
   - In the sidebar, select a gesture and assign an action (e.g., `volume_up`, `screenshot`, `win_tab`).
3. **Floating Window**:
   - Click the **FLOAT** button in the top bar to detach the camera view.
   - Drag the floating window anywhere on your screen.

---

## ❓ Troubleshooting

- **Camera not opening?**
  - Ensure no other app (Zoom, Teams) is using the camera.
  - Check `config.py` to change `CAMERA_INDEX` if you have multiple cameras.
- **Gestures not triggering?**
  - Ensure your hand is well-lit.
  - Retrain the gesture in the "Train" tab if detection is spotty.
- **Mouse not moving?**
  - Ensure "Virtual Mouse" mode is active (Green Button).

---

## 📜 License
This project is open source. Feel free to modify and distribute!
