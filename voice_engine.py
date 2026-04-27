
import speech_recognition as sr
import threading
import pyautogui
import logging
import platform
import time

# Disable FailSafe
pyautogui.FAILSAFE = False

logger = logging.getLogger(__name__)

class VoiceEngine:
    def __init__(self):
        self.recognizer = sr.Recognizer()
        
        # SPEED OPTIMIZATION:
        # Lower pause_threshold: Detects end of speech faster (default 0.8)
        self.recognizer.pause_threshold = 0.5 
        # Phrase threshold: Minimum length of speech (default 0.3)
        self.recognizer.phrase_threshold = 0.3
        # Non-speaking duration: shorter time to give up
        self.recognizer.non_speaking_duration = 0.4

        self.is_listening = False
        self.lock = threading.Lock()
        
        self.recognizer.dynamic_energy_threshold = True

        # Target Apps (Removed restriction, but kept list for reference/future)
        self.target_apps = [] 

        # Auto Mode State
        self.auto_mode_active = False
        self.auto_thread = None
        self.stop_event = threading.Event()

    def get_active_window_title(self):
        """Returns the title of the active window (Windows only)."""
        if platform.system() != "Windows":
            return ""
        try:
            import win32gui
            window = win32gui.GetForegroundWindow()
            return win32gui.GetWindowText(window)
        except Exception as e:
            return ""

    def find_best_microphone(self):
        """Try to find a real microphone/headset."""
        best_index = None
        try:
            mics = sr.Microphone.list_microphone_names()
            for i, name in enumerate(mics):
                n = name.lower()
                if "headset" in n or "microphone" in n:
                    if "stereo mix" not in n:
                        best_index = i
                        break
            if best_index is not None:
                logger.info(f"Auto-selected microphone index {best_index}: {mics[best_index]}")
            else:
                logger.info("Using default system microphone")
            return best_index
        except Exception as e:
            logger.error(f"Error finding mic: {e}")
            return None

    def start_auto_mode(self):
        """Starts the background auto-listening loop."""
        if self.auto_mode_active: 
            return

        logger.info("Starting Auto Voice Mode (High Speed)...")
        self.auto_mode_active = True
        self.stop_event.clear()
        self.auto_thread = threading.Thread(target=self._auto_loop, daemon=True)
        self.auto_thread.start()

    def stop_auto_mode(self):
        """Stops the auto loop."""
        logger.info("Stopping Auto Voice Mode...")
        self.auto_mode_active = False
        self.stop_event.set()
        if self.auto_thread:
            self.auto_thread.join(timeout=1.0)
            self.auto_thread = None

    def _auto_loop(self):
        """
        OPTIMIZED LOOP: Keeps microphone open persistently.
        """
        mic_index = self.find_best_microphone()
        
        try:
            # Persistent context manager
            with sr.Microphone(device_index=mic_index) as source:
                logger.info("Microphone Initialized & Ready.")
                
                # Fast calibration
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)

                while not self.stop_event.is_set():
                    if not self.auto_mode_active:
                        break

                    try:
                        # Listen (Blocking with short timeouts to allow breaking loop)
                        # phrase_time_limit=10 means max phrase is 10s
                        # timeout here is "time to wait for START of speech"
                        audio = None
                        try:
                            # Listen!
                            audio = self.recognizer.listen(source, timeout=1.0, phrase_time_limit=10)
                        except sr.WaitTimeoutError:
                            # This is normal, just silence. Loop again.
                            continue

                        if audio:
                            # Process in background thread to avoid blocking listening?
                            # No, for speech-to-text, we usually want sequential typing.
                            self._process_audio(audio)
                        
                    except Exception as e:
                        logger.error(f"Loop Listening Error: {e}")
                        time.sleep(0.1)

        except Exception as e:
            logger.critical(f"Microphone Init Failed: {e}")
            self.auto_mode_active = False

    def _process_audio(self, audio):
        """Recognize and Type with Command Parsing"""
        try:
            # 'en-IN' for User Preference
            text = self.recognizer.recognize_google(audio, language='en-IN')
            if text:
                logger.info(f"Recognized: {text}")
                
                # Command Parsing
                lower_text = text.lower().strip()
                
                # Command: ENTER / OPEN (at end of phrase)
                if lower_text.endswith(" enter") or lower_text.endswith(" open"):
                    # Strip the command word (last word)
                    # "search for cats enter" -> "search for cats"
                    words = text.split()
                    content = " ".join(words[:-1]) 
                    
                    if content:
                        pyautogui.write(content)
                    
                    logger.info("Command: ENTER")
                    pyautogui.press('enter')
                
                # Command: Just "Enter"
                elif lower_text == "enter" or lower_text == "open":
                    logger.info("Command: ENTER (Direct)")
                    pyautogui.press('enter')
                    
                else:
                    # Normal Typing
                    pyautogui.write(text + " ", interval=0)
                    
        except sr.UnknownValueError:
            pass # Silence/Noise
        except sr.RequestError:
            pass # Network issue

    def listen_and_type(self, auto=False):
        """Legacy One-Shot Method (Used by Gesture Action)"""
        if self.is_listening: return
        with self.lock: self.is_listening = True
        try:
            mic_index = self.find_best_microphone()
            with sr.Microphone(device_index=mic_index) as source:
                audio = self.recognizer.listen(source, timeout=3, phrase_time_limit=10)
                self._process_audio(audio)
        except: pass
        finally:
            with self.lock: self.is_listening = False

