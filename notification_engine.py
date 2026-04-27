import logging
import time
import requests
import json
import threading
from datetime import datetime

logger = logging.getLogger(__name__)

class NotificationEngine:
    def __init__(self, webhook_url=None):
        self.enabled = True
        self.webhook_url = webhook_url
        logger.info("Notification Engine Initialized")

    def send_attendance_alert(self, student_name, roll_number):
        """Sends a real-world webhook alert to Slack/Discord or falls back to logger."""
        if not self.enabled:
            return

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        message = f"✅ **Check-in Alert:** {student_name} (ID: {roll_number}) marked present at {timestamp}."
        
        # Non-blocking remote network request for industry robustness
        if self.webhook_url:
            threading.Thread(target=self._send_webhook, args=(message,), daemon=True).start()
        else:
            logger.info(f"[NATIVE ALERT] {message}")

    def _send_webhook(self, message):
        try:
            payload = {"content": message}
            headers = {"Content-Type": "application/json"}
            requests.post(self.webhook_url, data=json.dumps(payload), headers=headers, timeout=3)
        except Exception as e:
            logger.error(f"Failed to push webhook notification: {e}")

    def toggle(self, status):
        self.enabled = status
        logger.info(f"Notifications {'enabled' if status else 'disabled'}")
