# Hand2.0 Real-World Deployment Guide 🌍

This guide provides technical specifications for deploying the **Hand Gesture Control System** in production environments (Schools, Offices, Hospitals).

## 1. Hardware Recommendations 💻

### Camera Selection
- **Resolution**: Minimum 720p (1280x720). 1080p is preferred for high-ceiling or large-room installations.
- **Framerate**: 30 FPS minimum. Global Shutter cameras are recommended for high-speed industrial environments.
- **Lighting**: Wide dynamic range (WDR) cameras are essential if the kiosk is near windows with direct sunlight.

### Compute Module
- **Desktop**: Intel i5-10th Gen / Ryzen 5 or higher. NVIDIA GPU (GTX 1650+) significantly improves inference stability.
- **Edge**: Jetson Nano or Orin (requires specialized Mediapipe builds).

## 2. Environment Setup 🏗️

### Mounting Angle
- The camera should be mounted at chest level, angled slightly upwards or directly forward.
- **Background**: Avoid direct light sources (lamps, windows) behind the user's hand. Plain, non-reflective backgrounds are best.

### Distance
- Users should stand **0.5m to 1.5m** from the camera for optimal detection.

## 3. Software Optimization (Kiosk Mode) 🖥️

For a professional "Real World" feel, configure the Windows environment as follow:

1. **Auto-Start**:
   - Save `start_desktop.bat` in the Windows Startup folder (`shell:startup`).
2. **Kiosk Mode**:
   - Use Windows "Assigned Access" to lock the PC to the Chrome/WebView window.
   - Set the Taskbar to "Auto-hide".
3. **Power Settings**:
   - Set "Sleep" and "Screen Off" to **Never**.

## 4. Maintenance & Support 🛠️

- **Database Backups**: The `attendance.db` is a standard SQLite file. Schedule daily backups to a cloud drive.
- **Privacy Compliance**: Hand2.0 processes all data locally. Ensure signage is present to inform users that "Image data is processed real-time and not stored permanently (only landmark coordinates are used for identification)."

---
> [!IMPORTANT]
> **Production Safety**: Always enable the "Consensus Filter" in `config.py` to prevent accidental triggers from background movement.
