import pyautogui
import json
import os
import subprocess
import ctypes
import time
import math
import tkinter as tk
from tkinter import filedialog, simpledialog
from urllib.parse import quote
from pypdf import PdfReader, PdfWriter
import threading
from voice_engine import VoiceEngine

# For active window detection
try:
    import win32gui
    import win32process
    import psutil
except ImportError:
    win32gui = None
    win32process = None
    psutil = None

class ActionMap:
    def __init__(self, config_file="action_config.json"):
        self.config_file = config_file
        self.mapping_data = self.load_mapping()
        # Backward compatibility for existing mapping attribute
        self.mapping = self.mapping_data.get("profiles", {}).get("default", {}).get("default", {})
        self.voice_engine = VoiceEngine()
        self.save_lock = threading.Lock()
        
        # Configuration for pyautogui
        pyautogui.FAILSAFE = False # Prevent fail-safe corner triggers which can be annoying with hand tracking
        pyautogui.PAUSE = 0 # CRITICAL FIX: Disable PyAutoGUI artificial 0.1s delay which freezes the camera thread
        self.screen_w, self.screen_h = pyautogui.size()
        
        # Smoothing for mouse
        self.prev_x, self.prev_y = 0, 0
        self.smooth_factor = 0.2 # Lower = smoother but more lag
        
        # Smart Mouse State
        self.is_left_clicked = False
        self.last_right_click_time = 0

    def load_mapping(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    data = json.load(f)
                    # If it's the old flat structure, migrate it
                    if "profiles" not in data:
                        new_data = {
                            "profiles": {
                                "default": {
                                    "default": data,
                                    "apps": {}
                                }
                            }
                        }
                        return new_data
                    return data
            except:
                pass
        
        # Default if no config
        default_map = {
            "profiles": {
                "default": {
                    "default": {
                        "fist": "volume_mute",
                        "open_palm": "play_pause",
                        "peace": "screenshot",
                        "thumbs_up": "volume_up",
                        "thumbs_down": "volume_down"
                    },
                    "apps": {}
                }
            }
        }
        # Save default
        with open(self.config_file, 'w') as f:
            json.dump(default_map, f, indent=4)
        return default_map

    def save_mapping(self):
        with self.save_lock:
            try:
                with open(self.config_file, 'w') as f:
                    json.dump(self.mapping_data, f, indent=4)
                return True
            except Exception as e:
                print(f"Error saving mapping: {e}")
                return False

    def _apply_mapping_logic(self, gesture_name, action_name, app_name=None):
        print(f"[DEBUG] Mapping gesture '{gesture_name}' to action '{action_name}' (App: {app_name or 'Global'})")
        if app_name:
            if "profiles" not in self.mapping_data: self.mapping_data["profiles"] = {}
            if "default" not in self.mapping_data["profiles"]: self.mapping_data["profiles"]["default"] = {}
            if "apps" not in self.mapping_data["profiles"]["default"]:
                self.mapping_data["profiles"]["default"]["apps"] = {}
            if app_name not in self.mapping_data["profiles"]["default"]["apps"]:
                self.mapping_data["profiles"]["default"]["apps"][app_name] = {}
            
            if action_name == "":
                # Reset to default
                if gesture_name in self.mapping_data["profiles"]["default"]["apps"][app_name]:
                    del self.mapping_data["profiles"]["default"]["apps"][app_name][gesture_name]
                    print(f"[DEBUG] Reset app mapping for {gesture_name}")
                    # Clean up empty app entry
                    if not self.mapping_data["profiles"]["default"]["apps"][app_name]:
                        del self.mapping_data["profiles"]["default"]["apps"][app_name]
            else:
                self.mapping_data["profiles"]["default"]["apps"][app_name][gesture_name] = action_name
                print(f"[DEBUG] Set app mapping: {app_name} | {gesture_name} -> {action_name}")
        else:
            # Ensure path exists
            if "profiles" not in self.mapping_data: self.mapping_data["profiles"] = {}
            if "default" not in self.mapping_data["profiles"]: self.mapping_data["profiles"]["default"] = {}
            if "default" not in self.mapping_data["profiles"]["default"]: self.mapping_data["profiles"]["default"]["default"] = {}
            
            # Re-sync self.mapping reference just in case
            self.mapping = self.mapping_data["profiles"]["default"]["default"]
            
            if action_name == "":
                if gesture_name in self.mapping:
                    del self.mapping[gesture_name]
                    print(f"[DEBUG] Deleted global mapping for {gesture_name}")
            else:
                self.mapping[gesture_name] = action_name
                print(f"[DEBUG] Set global mapping: {gesture_name} -> {action_name}")

    def map_gesture(self, gesture_name, action_name, app_name=None):
        self._apply_mapping_logic(gesture_name, action_name, app_name)
        return self.save_mapping()

    def map_gestures_bulk(self, app_name, mappings):
        if not app_name or not isinstance(mappings, dict):
            return False
        for gesture, action in mappings.items():
            self._apply_mapping_logic(gesture, action, app_name)
        return self.save_mapping()

    def get_app_specific_action(self, gesture_name, app_name):
        """Helper for external callers (like Presentation mode) to check for app overrides."""
        if not app_name:
            return None
        apps_mapping = self.mapping_data.get("profiles", {}).get("default", {}).get("apps", {})
        
        # 1. Exact Match
        if app_name in apps_mapping:
            return apps_mapping[app_name].get(gesture_name)
            
        # 2. Case-insensitive and .exe fallback
        for configured_app, mapping in apps_mapping.items():
            if configured_app.lower() == app_name.lower() or configured_app.lower() == f"{app_name.lower()}.exe":
                return mapping.get(gesture_name)
                
        return None

    def get_active_app(self):
        """
        Identify foreground app using only native ultra-fast APIs. 
        Avoids psutil WMI calls which can cause massive GIL deadlocks on Windows 11.
        """
        now = time.time()
        if not hasattr(self, '_last_app_check_time'):
            self._last_app_check_time = 0
            self._last_active_app = None
            
        # Cache for 2 seconds
        if now - self._last_app_check_time < 2.0:
            return self._last_active_app

        if not win32gui:
            return self._last_active_app or "Desktop"

        try:
            hwnd = win32gui.GetForegroundWindow()
            if not hwnd: return "Desktop"
            
            # 1. Get Window Title (for friendly matching)
            title = win32gui.GetWindowText(hwnd).lower()
            
            # 2. Get Process Name (for robust matching)
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                proc = psutil.Process(pid)
                process_name = proc.name().lower()
            except:
                process_name = ""

            app_title = "Desktop"
            if "chrome" in title or "chrome" in process_name: app_title = "Chrome"
            elif "msedge" in process_name or "edge" in title: app_title = "Edge"
            elif "powerpnt" in process_name or "powerpoint" in title: app_title = "Powerpoint"
            elif "vlc" in process_name or "vlc" in title: app_title = "VLC"
            elif "spotify" in process_name or "spotify" in title: app_title = "Spotify"
            elif "notepad" in process_name: app_title = "Notepad"
            elif process_name:
                # Fallback to pure process name if no friendly match
                app_title = process_name
            
            self._last_app_check_time = now
            self._last_active_app = app_title
            return app_title
        except:
            self._last_app_check_time = now
            return self._last_active_app or "Desktop"

    def get_running_apps(self):
        if not win32gui or not psutil:
            return []
        
        apps = set()
        def enum_windows(hwnd, _):
            if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd):
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                try:
                    proc = psutil.Process(pid)
                    app_name = proc.name().lower()
                    if app_name.endswith('.exe'):
                        app_name = app_name[:-4]
                    apps.add(app_name.title())
                except:
                    pass
        
        win32gui.EnumWindows(enum_windows, None)
        return sorted(list(apps))

    def rename_mapping(self, old_gesture, new_gesture):
        # 1. Rename in Global default mapping
        if old_gesture in self.mapping:
            action = self.mapping.pop(old_gesture)
            self.mapping[new_gesture] = action
        
        # 2. Rename in App-specific mappings
        apps_mapping = self.mapping_data.get("profiles", {}).get("default", {}).get("apps", {})
        for app_name, app_map in apps_mapping.items():
            if old_gesture in app_map:
                action = app_map.pop(old_gesture)
                app_map[new_gesture] = action
                
        # 3. Rename in any other profiles (if any exist)
        for profile_name, profile_data in self.mapping_data.get("profiles", {}).items():
            if profile_name == "default": continue # already handled
            
            # Check default map in this profile
            p_default = profile_data.get("default", {})
            if old_gesture in p_default:
                action = p_default.pop(old_gesture)
                p_default[new_gesture] = action
            
            # Check apps map in this profile
            p_apps = profile_data.get("apps", {})
            for app_name, app_map in p_apps.items():
                if old_gesture in app_map:
                    action = app_map.pop(old_gesture)
                    app_map[new_gesture] = action

        return self.save_mapping()

    # --- Media ---
    def _action_media_play_pause(self): pyautogui.press('playpause')
    def _action_media_stop(self): pyautogui.press('stop')
    def _action_media_next(self): pyautogui.press('nexttrack')
    def _action_media_prev(self): pyautogui.press('prevtrack')
    def _action_media_seek_forward(self): pyautogui.press('right')
    def _action_media_seek_backward(self): pyautogui.press('left')
    def _action_volume_mute(self): pyautogui.press('volumemute')
    def _action_volume_up(self): pyautogui.press('volumeup')
    def _action_volume_down(self): pyautogui.press('volumedown')

    # --- Photoshop (Design) ---
    def _action_photoshop_brush_increase(self): pyautogui.press(']')
    def _action_photoshop_brush_decrease(self): pyautogui.press('[')


    # --- Browser ---
    def _action_browser_new_tab(self): pyautogui.hotkey('ctrl', 't')
    def _action_browser_close_tab(self): pyautogui.hotkey('ctrl', 'w')
    def _action_browser_reopen_tab(self): pyautogui.hotkey('ctrl', 'shift', 't')
    def _action_browser_next_tab(self): pyautogui.hotkey('ctrl', 'tab')
    def _action_browser_prev_tab(self): pyautogui.hotkey('ctrl', 'shift', 'tab')
    def _action_browser_refresh(self): pyautogui.hotkey('ctrl', 'r')
    def _action_browser_history(self): pyautogui.hotkey('ctrl', 'h')
    def _action_browser_downloads(self): pyautogui.hotkey('ctrl', 'j')

    # --- Productivity ---
    def _action_copy(self): pyautogui.hotkey('ctrl', 'c')
    def _action_paste(self): pyautogui.hotkey('ctrl', 'v')
    def _action_cut(self): pyautogui.hotkey('ctrl', 'x')
    def _action_undo(self): pyautogui.hotkey('ctrl', 'z')
    def _action_redo(self): pyautogui.hotkey('ctrl', 'y')
    def _action_select_all(self): pyautogui.hotkey('ctrl', 'a')
    def _action_save(self): pyautogui.hotkey('ctrl', 's')
    def _action_print(self): pyautogui.hotkey('ctrl', 'p')
    def _action_zoom_in(self): pyautogui.hotkey('ctrl', '+')
    def _action_zoom_out(self): pyautogui.hotkey('ctrl', '-')

    # --- Navigation ---
    def _action_scroll_up(self): pyautogui.scroll(40)
    def _action_scroll_down(self): pyautogui.scroll(-40)
    
    def _action_dynamic_scroll(self, landmarks):
        if not landmarks: return
        # Use Index Finger Tip (8)
        y = landmarks[8].y
        
        # Deadzone 0.4 - 0.6
        scroll_amount = 0
        if y < 0.4: # Top of screen -> Scroll Up
            dist = 0.4 - y
            scroll_amount = int(dist * 400) # Max ~160
        elif y > 0.6: # Bottom of screen -> Scroll Down
            dist = y - 0.6
            scroll_amount = -int(dist * 400)
            
        if scroll_amount != 0:
            pyautogui.scroll(scroll_amount)

    def _action_page_up(self): pyautogui.press('pageup')
    def _action_page_down(self): pyautogui.press('pagedown')
    def _action_arrow_up(self): pyautogui.press('up')
    def _action_arrow_down(self): pyautogui.press('down')
    def _action_arrow_left(self): pyautogui.press('left')
    def _action_arrow_right(self): pyautogui.press('right')

    # --- Extended Browser ---
    def _action_browser_bookmarks(self): pyautogui.hotkey('ctrl', 'd')
    def _action_browser_dev_tools(self): pyautogui.hotkey('f12')
    def _action_browser_find(self): pyautogui.hotkey('ctrl', 'f')
    def _action_browser_home(self): pyautogui.hotkey('alt', 'home')
    def _action_browser_back(self): pyautogui.hotkey('alt', 'left')
    def _action_browser_forward(self): pyautogui.hotkey('alt', 'right')
    def _action_browser_zoom_reset(self): pyautogui.hotkey('ctrl', '0')
    def _action_browser_incognito(self): pyautogui.hotkey('ctrl', 'shift', 'n')
    def _action_browser_fullscreen(self): pyautogui.press('f11')
    def _action_browser_print(self): pyautogui.hotkey('ctrl', 'p')

    # --- System & OS Additions ---
    def _action_system_task_manager(self): pyautogui.hotkey('ctrl', 'shift', 'esc')
    def _action_system_settings(self): pyautogui.hotkey('win', 'i')
    def _action_system_explorer(self): pyautogui.hotkey('win', 'e')
    def _action_system_lock(self): pyautogui.hotkey('win', 'l')
    def _action_system_snip(self): pyautogui.hotkey('win', 'shift', 's')
    def _action_system_action_center(self): pyautogui.hotkey('win', 'a')
    def _action_system_dictation(self): pyautogui.hotkey('win', 'h')
    def _action_system_run(self): pyautogui.hotkey('win', 'r')
    def _action_system_emoji(self): pyautogui.hotkey('win', '.')
    def _action_system_clipboard(self): pyautogui.hotkey('win', 'v')
    def _action_system_project(self): pyautogui.hotkey('win', 'p')
    def _action_system_search(self): pyautogui.hotkey('win', 's')
    def _action_system_notifications(self): pyautogui.hotkey('win', 'n')
    def _action_system_widgets(self): pyautogui.hotkey('win', 'w')
    def _action_system_desktop(self): pyautogui.hotkey('win', 'd')

    # --- Video Conferencing (Zoom / Teams / Meet) ---
    def _action_meeting_mute_mic(self): pyautogui.hotkey('ctrl', 'shift', 'm') 
    def _action_meeting_video_toggle(self): pyautogui.hotkey('ctrl', 'shift', 'o') 
    def _action_meeting_share_screen(self): pyautogui.hotkey('ctrl', 'shift', 's')
    def _action_meeting_leave(self): pyautogui.hotkey('alt', 'q')
    def _action_meeting_chat(self): pyautogui.hotkey('alt', 'h')
    def _action_meeting_raise_hand(self): pyautogui.hotkey('alt', 'y')
    def _action_meeting_record(self): pyautogui.hotkey('alt', 'r')
    def _action_meeting_participants(self): pyautogui.hotkey('alt', 'u')

    # --- Coding & IDE (VS Code) ---
    def _action_ide_format_code(self): pyautogui.hotkey('shift', 'alt', 'f')
    def _action_ide_comment_line(self): pyautogui.hotkey('ctrl', '/')
    def _action_ide_find_all(self): pyautogui.hotkey('ctrl', 'shift', 'f')
    def _action_ide_terminal(self): pyautogui.hotkey('ctrl', '`')
    def _action_ide_command_palette(self): pyautogui.hotkey('ctrl', 'shift', 'p')
    def _action_ide_run_code(self): pyautogui.hotkey('ctrl', 'alt', 'n')
    def _action_ide_step_over(self): pyautogui.press('f10')
    def _action_ide_step_into(self): pyautogui.press('f11')
    def _action_ide_breakpoint(self): pyautogui.press('f9')
    def _action_ide_go_to_line(self): pyautogui.hotkey('ctrl', 'g')
    def _action_ide_rename_symbol(self): pyautogui.press('f2')
    def _action_ide_save_all(self): pyautogui.hotkey('ctrl', 'k', 's')
    def _action_ide_close_folder(self): pyautogui.hotkey('ctrl', 'k', 'f')

    # --- Spreadsheet & Excel ---
    def _action_excel_new_sheet(self): pyautogui.hotkey('shift', 'f11')
    def _action_excel_sum(self): pyautogui.hotkey('alt', '=')
    def _action_excel_format_currency(self): pyautogui.hotkey('ctrl', 'shift', '$')
    def _action_excel_format_percent(self): pyautogui.hotkey('ctrl', 'shift', '%')
    def _action_excel_filter(self): pyautogui.hotkey('ctrl', 'shift', 'l')
    def _action_excel_chart(self): pyautogui.press('f11')
    def _action_excel_select_column(self): pyautogui.hotkey('ctrl', 'space')
    def _action_excel_select_row(self): pyautogui.hotkey('shift', 'space')

    # --- Gaming & WASD Dynamics ---
    def _action_game_move_forward(self): pyautogui.press('w')
    def _action_game_move_backward(self): pyautogui.press('s')
    def _action_game_move_left(self): pyautogui.press('a')
    def _action_game_move_right(self): pyautogui.press('d')
    def _action_game_jump(self): pyautogui.press('space')
    def _action_game_crouch(self): pyautogui.press('c')
    def _action_game_sprint(self): pyautogui.press('shift')
    def _action_game_reload(self): pyautogui.press('r')
    def _action_game_interact(self): pyautogui.press('e')
    def _action_game_inventory(self): pyautogui.press('i')
    def _action_game_map(self): pyautogui.press('m')
    def _action_game_menu(self): pyautogui.press('esc')

    # --- Photoshop & Advanced Design ---
    def _action_photoshop_new_layer(self): pyautogui.hotkey('ctrl', 'shift', 'n')
    def _action_photoshop_undo(self): pyautogui.hotkey('ctrl', 'z')
    def _action_photoshop_redo(self): pyautogui.hotkey('ctrl', 'shift', 'z')
    def _action_photoshop_deselect(self): pyautogui.hotkey('ctrl', 'd')
    def _action_photoshop_invert(self): pyautogui.hotkey('ctrl', 'i')
    def _action_photoshop_transform(self): pyautogui.hotkey('ctrl', 't')
    def _action_photoshop_fill(self): pyautogui.hotkey('shift', 'f5')
    def _action_photoshop_zoom_fit(self): pyautogui.hotkey('ctrl', '0')
    def _action_photoshop_merge_layers(self): pyautogui.hotkey('ctrl', 'e')
    def _action_photoshop_export(self): pyautogui.hotkey('ctrl', 'shift', 'alt', 'w')

    # --- Window Management ---
    def _action_minimize_window(self): pyautogui.hotkey('win', 'down')
    def _action_maximize_window(self): pyautogui.hotkey('win', 'up')
    def _action_restore_window(self): pyautogui.hotkey('win', 'shift', 'up') # Or down usually works to restore from max
    def _action_close_current_window(self): pyautogui.hotkey('alt', 'f4')
    def _action_alt_tab(self): pyautogui.hotkey('alt', 'tab')
    def _action_win_tab(self): pyautogui.hotkey('win', 'tab')
    def _action_show_desktop(self): pyautogui.hotkey('win', 'd')

    # --- Mouse ---
    def _action_left_click(self): pyautogui.click()
    def _action_right_click(self): pyautogui.click(button='right')
    def _action_middle_click(self): pyautogui.click(button='middle')
    def _action_double_click(self): pyautogui.doubleClick()

    def _action_track_cursor(self, landmarks):
        if not landmarks: return
        # Index finger tip is 8
        tip = landmarks[8]
        
        # Mapping coordinates 0-1 to screen pixels
        # Direct x mapping (0->0, 1->1) for mirrored feed logic
        target_x = tip.x * self.screen_w
        target_y = tip.y * self.screen_h
        
        # Zero-latency instant cursor update (Bypassing PyAutoGUI overhead)
        # We rely entirely on the upstream Kalman Filter for smoothing! Redundant EMA smoothing here caused 'dragging' delays.
        self.prev_x = target_x
        self.prev_y = target_y
        
        try:
            ctypes.windll.user32.SetCursorPos(int(target_x), int(target_y))
        except Exception:
            # Fallback if ctypes fails for some reason
            pyautogui.moveTo(target_x, target_y)

    # --- Smart Mouse v2 ---
    def _action_smart_mouse(self, landmarks):
        if not landmarks: return
        
        # Landmarks:
        # 4 = Thumb Tip, 8 = Index Tip
        # 5 = Index MCP (Base of Index), 2 = Thumb MCP
        
        thumb_tip = landmarks[4]
        index_tip = landmarks[8]
        index_mcp = landmarks[5]
        
        # Helper for distance (normalized coords)
        def dist(p1, p2):
            return math.hypot(p1.x - p2.x, p1.y - p2.y)
            
        # 1. Logic Definitions
        # "Close Thumb" -> Thumb Tip (4) close to Index Base (5)
        thumb_closed_dist = dist(thumb_tip, index_mcp)
        
        # "Close Only Index" -> Index Tip (8) curled down to MCP (5)
        index_closed_dist = dist(index_tip, index_mcp)
        
        # Thresholds
        CLICK_THRESHOLD = 0.1
        
        # 2. Right Click Logic: "Close Only Index"
        # Condition: Index is curled AND Thumb is NOT curled (open)
        if index_closed_dist < CLICK_THRESHOLD and thumb_closed_dist > CLICK_THRESHOLD:
            # Ensure Left Click is released if we switch to Right Click (safety)
            if self.is_left_clicked:
                pyautogui.mouseUp()
                self.is_left_clicked = False

            current_time = time.time()
            if current_time - self.last_right_click_time > 1.0: # Cooldown
                pyautogui.click(button='right')
                self.last_right_click_time = current_time
            # Locking cursor while clicking prevents jitter
            return 

        # 3. Left Click Logic: "Close Thumb"
        # Condition: Thumb is curled (Index should be open usually for tracking)
        is_thumb_closed = thumb_closed_dist < CLICK_THRESHOLD
        
        if is_thumb_closed:
            if not self.is_left_clicked:
                pyautogui.mouseDown()
                self.is_left_clicked = True
        else:
            if self.is_left_clicked:
                pyautogui.mouseUp()
                self.is_left_clicked = False

        # 4. Cursor Tracking
        # Only track if not right-clicking (which we returned from already)
        self._action_track_cursor(landmarks)

    def is_continuous(self, gesture_name):
        # Check active app mapping first
        active_app = self.get_active_app()
        action = self.get_app_specific_action(gesture_name, active_app)
        
        # Fallback to default mapping
        if not action:
            action = self.mapping.get(gesture_name)
            
        if not action: return False
        return action in ["track_cursor", "smart_mouse", "scroll_up", "scroll_down", "volume_up", "volume_down", "dynamic_scroll"]

    # --- System ---
    def _action_screenshot(self): pyautogui.hotkey('win', 'printscreen')
    def _action_lock_screen(self): ctypes.windll.user32.LockWorkStation()
    def _action_task_manager(self): pyautogui.hotkey('ctrl', 'shift', 'esc')
    def _action_file_explorer(self): pyautogui.hotkey('win', 'e')
    def _action_settings(self): pyautogui.hotkey('win', 'i')
    def _action_enter(self): pyautogui.press('enter')
    def _action_space(self): pyautogui.press('space')
    def _action_esc(self): pyautogui.press('esc')
    def _action_backspace(self): pyautogui.press('backspace')
    def _action_tab(self): pyautogui.press('tab')

    # --- Window Snapping ---
    def _action_snap_window_left(self): pyautogui.hotkey('win', 'left')
    def _action_snap_window_right(self): pyautogui.hotkey('win', 'right')
    
    # --- Virtual Desktops ---
    def _action_desktop_next(self): pyautogui.hotkey('win', 'ctrl', 'right')
    def _action_desktop_prev(self): pyautogui.hotkey('win', 'ctrl', 'left')
    def _action_desktop_new(self): pyautogui.hotkey('win', 'ctrl', 'd')
    def _action_desktop_close(self): pyautogui.hotkey('win', 'ctrl', 'f4')

    # --- System Tools ---
    def _action_open_start_menu(self): pyautogui.press('win')
    def _action_emoji_panel(self): pyautogui.hotkey('win', '.')
    def _action_clipboard_history(self): pyautogui.hotkey('win', 'v')
    def _action_run_dialog(self): pyautogui.hotkey('win', 'r')
    
    # --- Browser Extra ---
    def _action_browser_focus_address(self): pyautogui.hotkey('alt', 'd')

    # --- PowerPoint ---
    def _action_ppt_next(self): pyautogui.press('right')
    def _action_ppt_prev(self): pyautogui.press('left')
    def _action_ppt_start(self): pyautogui.press('f5')
    def _action_ppt_stop(self): pyautogui.press('esc')
    def _action_ppt_black_screen(self): pyautogui.press('b')
    def _action_ppt_white_screen(self): pyautogui.press('w')
    def _action_ppt_laser_pointer(self): pyautogui.hotkey('ctrl', 'l')
    def _action_ppt_pen(self): pyautogui.hotkey('ctrl', 'p')

    # --- Word / Document ---
    def _action_word_bold(self): pyautogui.hotkey('ctrl', 'b')
    def _action_word_italic(self): pyautogui.hotkey('ctrl', 'i')
    def _action_word_underline(self): pyautogui.hotkey('ctrl', 'u')
    def _action_word_align_center(self): pyautogui.hotkey('ctrl', 'e')
    def _action_word_align_left(self): pyautogui.hotkey('ctrl', 'l')
    def _action_word_align_right(self): pyautogui.hotkey('ctrl', 'r')

    # --- System Power ---
    def _action_shutdown(self): 
        # Non-blocking shutdown command
        subprocess.Popen("shutdown /s /t 60", shell=True) 
    def _action_restart(self): 
        subprocess.Popen("shutdown /r /t 60", shell=True)
    def _action_sleep(self):
        # Sleep is inherently blocking in some ways but this is the best we can do
        subprocess.Popen("rundll32.exe powrprof.dll,SetSuspendState 0,1,0", shell=True)

    # --- App Launchers ---
    def _action_open_calculator(self): subprocess.Popen("calc", shell=True)
    def _action_open_notepad(self): subprocess.Popen("notepad", shell=True)
    def _action_open_cmd(self): subprocess.Popen("start cmd", shell=True)
    
    # --- PDF Tools ---
    def _action_split_pdf(self):
        """
        Signals to the frontend that a PDF split UI should be shown.
        Actual processing happens via a separate API call.
        """
        # We just return the action name, the server/frontend will handle the rest.
        return "split_pdf"

    # --- Voice Typing ---
    def _action_voice_type(self):
        # Run in a separate thread so we don't block the main loop
        import threading
        t = threading.Thread(target=self.voice_engine.listen_and_type)
        t.daemon = True
        t.start()
    
    # --- Custom Logic Helpers ---
    def _execute_type_text(self, text):
        import threading
        def type_it():
            try:
                pyautogui.write(text, interval=0.04)
            except:
                pass
        threading.Thread(target=type_it, daemon=True).start()
    
    def _execute_custom_cmd(self, cmd):
        # clean command
        cmd = cmd.strip()
        lower_cmd = cmd.lower()
        
        print(f"[DEBUG] Custom Command: {cmd}")

        import webbrowser
        import re
        import shutil

        # Helper to get specific browser controller
        def get_browser(txt):
            try:
                if 'chrome' in txt:
                    return webbrowser.get('google-chrome')
                if 'edge' in txt:
                    return webbrowser.get('windows-default') 
                if 'firefox' in txt:
                    return webbrowser.get('firefox')
            except:
                return None
            return None

        # 1. URL Detection (Prioritize explicit URLs)
        if re.match(r'^(http|www\.|[a-z0-9]+\.[a-z]{2,})', lower_cmd):
             if not lower_cmd.startswith('http'):
                 url = 'https://' + cmd
             else:
                 url = cmd
             webbrowser.open(url)
             return True

        # 2. Logic for "Close [target]"
        if lower_cmd.startswith("close ") or lower_cmd.startswith("exit ") or lower_cmd.startswith("kill "):
            # Extract target
            if lower_cmd.startswith("close"): target = lower_cmd[6:].strip()
            elif lower_cmd.startswith("exit"): target = lower_cmd[5:].strip()
            else: target = lower_cmd[5:].strip()
            
            # Map friendly names to Process Names (.exe)
            # Use 'tasklist' manually to find these if unsure, but standard ones are:
            proc_map = {
                "chrome": "chrome.exe",
                "google chrome": "chrome.exe",
                "browser": "chrome.exe",
                "firefox": "firefox.exe",
                "edge": "msedge.exe",
                "microsoft edge": "msedge.exe",
                "notepad": "notepad.exe",
                "calculator": "CalculatorApp.exe",
                "calc": "CalculatorApp.exe",
                "whatsapp": "WhatsApp.exe",
                "spotify": "Spotify.exe",
                "vlc": "vlc.exe",
                "media player": "vlc.exe",
                "word": "WINWORD.EXE",
                "winword": "WINWORD.EXE",
                "microsoft word": "WINWORD.EXE",
                "excel": "EXCEL.EXE",
                "microsoft excel": "EXCEL.EXE",
                "powerpoint": "POWERPNT.EXE",
                "ppt": "POWERPNT.EXE",
                "microsoft powerpoint": "POWERPNT.EXE",
                "vs code": "Code.exe",
                "vscode": "Code.exe",
                "code": "Code.exe",
                "teams": "Teams.exe",
                "microsoft teams": "Teams.exe",
                "slack": "slack.exe",
                "discord": "Discord.exe",
                "zoom": "Zoom.exe",
                "paint": "mspaint.exe",
                "settings": "SystemSettings.exe",
                "explorer": "explorer.exe",
                "file explorer": "explorer.exe",
                "cmd": "cmd.exe",
                "command prompt": "cmd.exe",
                "powershell": "powershell.exe",
                "task manager": "Taskmgr.exe",
                # UWP Apps (Tricky, sometimes hosted in ApplicationFrameHost, but often have specific exe)
                "store": "WinStore.App.exe",
                "microsoft store": "WinStore.App.exe",
                "photos": "Microsoft.Photos.exe",
                "camera": "WindowsCamera.exe",
                "snipping tool": "SnippingTool.exe"
            }
            
            # Get process name
            proc_name = proc_map.get(target)
            
            # If not in map, try using the target as the process name directly (heuristic)
            if not proc_name:
                # If valid text, assume .exe
                if " " not in target:
                    proc_name = f"{target}.exe"
            
            if proc_name:
                print(f"[INFO] Closing process: {proc_name}")
                # /IM = Image Name, /F = Force
                try:
                    subprocess.Popen(f"taskkill /IM {proc_name} /F", shell=True)
                    return True
                except Exception as e:
                    print(f"Error closing {proc_name}: {e}")
            
            # If we couldn't even guess a process name (e.g. multi-word unknown app), 
            # maybe do nothing or inform? 
            # For now, if unknown, we just return True to avoid fallback to Search.
            return True


        # 3. Logic for "Open [target] in [browser]"
        browser_pref = None
        if "in google chrome" in lower_cmd or "in chrome" in lower_cmd:
            browser_pref = get_browser("chrome")
        elif "in firefox" in lower_cmd:
             browser_pref = get_browser("firefox")
        elif "in edge" in lower_cmd:
             browser_pref = get_browser("edge")
        
        clean_cmd = lower_cmd
        clean_cmd = re.sub(r'\s+in\s+(google\s+)?chrome', '', clean_cmd)
        clean_cmd = re.sub(r'\s+in\s+firefox', '', clean_cmd)
        clean_cmd = re.sub(r'\s+in\s+(microsoft\s+)?edge', '', clean_cmd)
        clean_cmd = re.sub(r'\s+in\s+browser', '', clean_cmd)
        clean_cmd = clean_cmd.strip()

        # 3. Handle "Open [target]" or just "[target]"
        target = clean_cmd
        if clean_cmd.startswith("open "):
            target = clean_cmd[5:].strip()

        # Shortcuts (Mixed Web/App)
        # For apps that have a web version, we list the LOCAL protocol first or just the name.
        # Logic below will try local first, then fallback to web if defined.
        shortcuts = {
            "youtube": "https://youtube.com",
            "google": "https://google.com",
            "facebook": "https://facebook.com",
            "instagram": "https://instagram.com",
            "whatsapp": "whatsapp:", 
            "whatsapp web": "https://web.whatsapp.com", 
            "whatsweb": "https://web.whatsapp.com",
            "spotify": "spotify:", 
            "gmail": "https://mail.google.com",
            "chatgpt": "https://chatgpt.com",
            
            # Dev Tools
            "vs code": "code",
            "vscode": "code",
            "code": "code",
            "cmd": "cmd",
            "command prompt": "cmd",
            "powershell": "powershell",

            # Office
            "word": "winword",
            "microsoft word": "winword",
            "excel": "excel",
            "microsoft excel": "excel",
            "powerpoint": "powerpnt",
            "ppt": "powerpnt",
            "microsoft powerpoint": "powerpnt",
            
            # Utilities
            "calculator": "calc",
            "calc": "calc",
            "notepad": "notepad",
            "paint": "mspaint",
            "explorer": "explorer",
            "file explorer": "explorer",
            "task manager": "taskmgr",
            "snipping tool": "snippingtool",

            # Windows Settings / UWP using Protocols (Safest way to launch)
            "settings": "ms-settings:",
            "store": "ms-windows-store:",
            "app store": "ms-windows-store:",
            "microsoft store": "ms-windows-store:", 
            "ms store": "ms-windows-store:",
            "camera": "microsoft.windows.camera:",
            "photos": "ms-photos:",
            "clock": "ms-clock:",
            "alarm": "ms-clock:",
            "todo": "ms-todo:",
            "weather": "bingweather:",
            "maps": "bingmaps:"
        }

        matched = shortcuts.get(target)

        # --- PATH A: User specified a browser ("in chrome") ---
        # STRICTLY Web Actions (URL or Search)
        if browser_pref:
             # If matched shortcut is a URL, use it
             if matched and matched.startswith("http"):
                 url = matched
             elif '.' in target and ' ' not in target:
                 url = 'https://' + target
             else:
                 # Fallback: Search
                 url = f"https://www.google.com/search?q={quote(target)}"
            
             browser_pref.open(url)
             return True

        # --- PATH B: No browser specified (Local App preferred) ---
        
        # Helper to launch and detect failure
        def try_launch_local(cmd):
            try:
                # STRATEGY: Use PowerShell Start-Process to force focus.
                # os.startfile often launches in background if Python doesn't have focus.
                # We also minimize the current window (Python/Console) momentarily maybe? No that's jarring.
                
                # Trick: Send an 'Alt' key press to wake up the UI thread? 
                # Better: Use PowerShell.
                
                # Handling shortcuts (protocols or paths) vs raw commands
                
                # 1. Try PowerShell Start-Process (most robust for Focus)
                # We use -PassThru to check existence? No, just run it.
                # Quotes are tricky.
                
                safe_cmd = cmd.replace("'", "''") # Escape for PS
                
                # "start" command in shell sometimes works better for focus than direct execution
                # But os.startfile is basically "start".
                
                # Let's try executing via 'start' explicitly in shell, which usually brings to front.
                # subprocess.Popen(f'start "" "{cmd}"', shell=True)
                
                # user reported background issue. Let's try the ForegroundLockTimeout trick? 
                # Or just use PowerShell which requests focus.
                
                # TRICK: Simulate "User Input" to bypass Windows ForegroundLockTimeout.
                # Windows prevents background apps from stealing focus unless user input is detected.
                # Pressing 'alt' is harmless (toggles menu bar) but resets the lock timer.
                try:
                    pyautogui.press('alt')
                except:
                    pass
                
                # Small delay to let Windows register the input
                # time.sleep(0.05) 

                ps_command = f"Start-Process '{safe_cmd}' -WindowStyle Normal"
                subprocess.Popen(["powershell", "-Command", ps_command], shell=True)
                
                return True
            except Exception as e:
                # print(f"DEBUG: PS Launch failed: {e}")
                # Fallback to os.startfile
                try:
                    os.startfile(cmd)
                    return True
                except:
                    return False

        # 1. Known Shortcut
        if matched:
            # If it's a web link, just open it (default browser)
            if matched.startswith("http"):
               webbrowser.open(matched)
               return True
            else:
               # Try local
               if try_launch_local(matched): return True

        # 2. Check if it's an executable in PATH (Old reliable)
        if shutil.which(target):
            if try_launch_local(target): return True

        # 3. Check for URL-like
        if '.' in target and ' ' not in target:
             webbrowser.open('https://' + target)
             return True
        
        # 4. Try generic local launch (The "If present, open it" rule)
        # Even if not in shortcut map, user might say "open figma".
        # os.startfile("figma") might work if "figma" is in path or registered.
        if try_launch_local(target):
             return True
        
        # 5. If "whatsapp" specifically failed local `whatsapp:` above (via shortcut),
        # maybe we should fallback to web version for convenience?
        if target == "whatsapp" or target == "spotify":
             # Special handling: User asked for app, app missing.
             # "sometime the app ... maynot be present ... perform the action"
             # Opening web version is a good fallback "action".
             if target == "whatsapp": webbrowser.open("https://web.whatsapp.com"); return True
             if target == "spotify": webbrowser.open("https://open.spotify.com"); return True
        
        # 6. ULTIMATE FALLBACK: Search Google
        print(f"[INFO] Command '{cmd}' fallback to Search")
        webbrowser.open(f"https://www.google.com/search?q={quote(cmd)}")
        return True

    def perform_action(self, action, landmarks=None):
        """
        Executes a specific action string directly.
        """
        # print(f"[DEBUG] Performing Action: '{action}'")
        
        if not action:
            return None

        # Check if it's a known method
        method_name = f"_action_{action}"
        if hasattr(self, method_name):
            method = getattr(self, method_name)
            try:
                if action == "track_cursor" and landmarks:
                    method(landmarks)
                # Smart Mouse also needs landmarks
                elif action == "smart_mouse" and landmarks:
                    method(landmarks)
                else:
                    method()
                # print(f"[DEBUG] Executed {method_name}")
                return action
            except Exception as e:
                print(f"[ERROR] Execution failed for {method_name}: {e}")
                return None
        
        # Text Macro Handler
        if action.startswith("type:"):
            text = action[5:]
            self._execute_type_text(text)
            return f"Typed: {text}"

        # Custom Command Handler
        if action.startswith("cmd:"):
            command = action[4:]
            self._execute_custom_cmd(command)
            return f"CMD: {command}"
        
        # Backward compatibility
        if action == "play_pause": self._action_media_play_pause(); return "media_play_pause"
        
        print(f"[DEBUG] No handler found for action: {action}")
        return None

    def execute(self, gesture_name, landmarks=None, app_name_override=None):
        # 1. Try App-Specific Mapping
        active_app = app_name_override or self.get_active_app()
        action = None
        
        if active_app:
            apps_mapping = self.mapping_data.get("profiles", {}).get("default", {}).get("apps", {})
            if active_app in apps_mapping:
                action = apps_mapping[active_app].get(gesture_name)
                
            # Backwards compatibility for old config names 
            if not action:
                for configured_app, mapping in apps_mapping.items():
                    if configured_app.lower() == active_app.lower() or configured_app.lower() == f"{active_app.lower()}.exe":
                        action = mapping.get(gesture_name)
                        if action:
                            active_app = configured_app # Log correctly
                            break

            if action:
                print(f"[DEBUG] App gesture: {active_app} | {gesture_name} -> {action}")
        
        # 2. Fallback to Default
        if not action:
            action = self.mapping.get(gesture_name)
            print(f"[DEBUG] Default gesture: '{gesture_name}' -> Action: '{action}'")
            
        return self.perform_action(action, landmarks)

    def get_available_actions(self):
        return [
            # Media
            "media_play_pause", "media_stop", "media_next", "media_prev",
            "media_seek_forward", "media_seek_backward",
            "volume_mute", "volume_up", "volume_down",
            
            # Browser Control
            "browser_new_tab", "browser_close_tab", "browser_reopen_tab",
            "browser_next_tab", "browser_prev_tab", "browser_focus_address",
            "browser_refresh", "browser_history", "browser_downloads",
            "browser_bookmarks", "browser_dev_tools", "browser_find", "browser_home",
            "browser_back", "browser_forward", "browser_zoom_reset",
            "browser_incognito", "browser_fullscreen", "browser_print",
            
            # Productivity
            "copy", "paste", "cut", "undo", "redo",
            "select_all", "save", "print", "zoom_in", "zoom_out",
            
            # Presentation (PPT)
            "ppt_next", "ppt_prev", "ppt_start", "ppt_stop", 
            "ppt_black_screen", "ppt_white_screen", "ppt_laser_pointer", "ppt_pen",
            
            # Document (Word)
            "word_bold", "word_italic", "word_underline",
            "word_align_center", "word_align_left", "word_align_right",
            
            # Spreadsheet (Excel)
            "excel_new_sheet", "excel_sum", "excel_format_currency", "excel_format_percent",
            "excel_filter", "excel_chart", "excel_select_column", "excel_select_row",

            # Video Conferencing (Meeting)
            "meeting_mute_mic", "meeting_video_toggle", "meeting_share_screen", "meeting_leave",
            "meeting_chat", "meeting_raise_hand", "meeting_record", "meeting_participants",

            # Coding (IDE)
            "ide_format_code", "ide_comment_line", "ide_find_all", "ide_terminal",
            "ide_command_palette", "ide_run_code", "ide_step_over", "ide_step_into",
            "ide_breakpoint", "ide_go_to_line", "ide_rename_symbol", "ide_save_all",
            "ide_close_folder",

            # Design Tools (Photoshop)
            "photoshop_brush_increase", "photoshop_brush_decrease",
            "photoshop_new_layer", "photoshop_undo", "photoshop_redo", "photoshop_deselect",
            "photoshop_invert", "photoshop_transform", "photoshop_fill", "photoshop_zoom_fit",
            "photoshop_merge_layers", "photoshop_export",

            # Gaming WASD
            "game_move_forward", "game_move_backward", "game_move_left", "game_move_right",
            "game_jump", "game_crouch", "game_sprint", "game_reload", "game_interact",
            "game_inventory", "game_map", "game_menu",
            
            # Navigation
            "dynamic_scroll", "scroll_up", "scroll_down", "page_up", "page_down",
            "arrow_up", "arrow_down", "arrow_left", "arrow_right",
            
            # Window Management
            "snap_window_left", "snap_window_right",
            "minimize_window", "maximize_window", "restore_window", "close_current_window",
            "alt_tab", "win_tab", "show_desktop",
            "desktop_next", "desktop_prev", "desktop_new", "desktop_close",

            # System & OS Options
            "system_task_manager", "system_settings", "system_explorer", "system_lock",
            "system_snip", "system_action_center", "system_dictation", "system_run",
            "system_emoji", "system_clipboard", "system_project", "system_search",
            "system_notifications", "system_widgets", "system_desktop",
            
            # Mouse
            "track_cursor", "left_click", "right_click", "double_click", "middle_click",
            
            # Legacy Controls
            "enter", "space", "esc", "backspace", "tab",
            
            # System & Power
            "shutdown", "restart", "sleep",
            "open_calculator", "open_notepad", "open_cmd",
            
            # Advanced
            "custom_command", "type_text",
            
            # PDF
            "split_pdf",

            # Voice
            "voice_type"
        ]
