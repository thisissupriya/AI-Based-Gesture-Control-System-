import webview
import threading
import time
import sys
from server import app, logger, camera_loop, state

class DesktopApi:
    def __init__(self):
        self._float_window = None

    def move_window(self, x, y):
        """Move the floating window to the specified coordinates."""
        if self._float_window:
            # Note: handle rounding as JS might pass floats
            self._float_window.move(int(x), int(y))

    def resize_window(self, width, height):
        """Resize the floating window."""
        if self._float_window:
            self._float_window.resize(int(width), int(height))

    def get_window_pos(self):
        """Get the current position of the floating window."""
        if self._float_window:
            return {'x': self._float_window.x, 'y': self._float_window.y}
        return None

    def toggle_floating_window(self):
        """Toggle the floating camera window."""
        if self._float_window:
            try:
                self._float_window.destroy()
            except:
                pass
            self._float_window = None
            state.floating_camera_active = False # Sync state
            logger.info("Closed Floating Window")
        else:
            # Create a small, frameless, always-on-top window
            width, height = 300, 200
            def on_float_closed():
                self._float_window = None
                state.floating_camera_active = False
                logger.info("Floating Window Closed (callback)")

            self._float_window = webview.create_window(
                'Float', 
                'http://127.0.0.1:5000/float',
                width=width,
                height=height,
                frameless=True,
                on_top=True,
                resizable=True,
                transparent=False, # Disable transparency temporarily to fix click-through issues
                min_size=(150, 100),
                easy_drag=True, # Enable built-in drag
                js_api=self, # Expose API to this window!
                x=0, y=0 # Will be positioned by OS or user
            )
            self._float_window.events.closed += on_float_closed
            state.floating_camera_active = True # Sync state
            logger.info("Opened Floating Window")

api = DesktopApi()


def run_flask():
    """Run the Flask server."""
    logger.info("Starting Flask Server for Desktop App...")
    # We set use_reloader=False to avoid issues with double threads in a frozen or desktop context
    app.run(host='127.0.0.1', port=5000, debug=False, threaded=True, use_reloader=False)

def start_desktop():
    """Initialize and start the desktop window."""
    # Start the background camera thread (usually started in server.py's __main__, 
    # but we are importing 'app' so we need to start it manually here)
    logger.info("Starting Background Camera Thread for Desktop...")
    t_camera = threading.Thread(target=camera_loop, daemon=True)
    t_camera.start()

    # Start Flask in a background thread
    t_flask = threading.Thread(target=run_flask, daemon=True)
    t_flask.start()

    # Wait a moment for the server to start
    time.sleep(2)

    # Define Native Menu
    try:
        from webview.menu import Menu, MenuAction, MenuSeparator
        
        def change_domain(domain, url):
            try:
                if state._desktop_window:
                    state._desktop_window.load_url(f'http://127.0.0.1:5000{url}')
                    logger.info(f"Switching to Domain: {domain}")
            except Exception as e:
                logger.error(f"Failed to change domain: {e}")

        def safe_refresh():
            try:
                if state._desktop_window:
                    state._desktop_window.evaluate_js('window.location.reload()')
            except Exception as e:
                logger.error(f"Failed to refresh: {e}")

        menu_items = [
            Menu(
                'Industry', 
                [
                    MenuAction('Hub / Home', lambda: change_domain('Home', '/')),
                    MenuSeparator(),
                    MenuAction('Presentation Mode', lambda: change_domain('Presentation', '/presentation')),
                    MenuAction('Automotive / Drive', lambda: change_domain('Drive', '/drive')),
                    MenuAction('Medical / Sterile', lambda: change_domain('Medical', '/medical')),
                    MenuAction('Education / Attendance', lambda: change_domain('Attendance', '/attendance')),
                ]
            ),
            Menu(
                'View',
                [
                    MenuAction('Toggle Float Window', api.toggle_floating_window),
                    MenuAction('Refresh', safe_refresh),
                ]
            )
        ]
    except ImportError:
        logger.warning("Native Menu not supported in this pywebview version")
        menu_items = []

    # Ensure pywebview starts or fallback to web browser
    import webbrowser
    try:
        # Create the webview window
        try:
            window = webview.create_window(
                'Hand Gesture Control - Enterprise Edition', 
                'http://127.0.0.1:5000',
                width=1280,
                height=850,
                min_size=(1000, 700),
                js_api=api
            )
        except TypeError:
            window = webview.create_window(
                'Hand Gesture Control', 
                'http://127.0.0.1:5000',
                width=1280,
                height=850,
                min_size=(1000, 700),
                js_api=api
            )

        state._desktop_window = window
        logger.info("Launching Desktop Window...")
        webview.start(menu=menu_items)
    except Exception as e:
        state._desktop_window = None
        logger.warning(f"Native Desktop Window failed: {e}")
        logger.info("Falling back to Default Web Browser...")
        webbrowser.open('http://127.0.0.1:5000')
        logger.info("Server is running. Press CTRL+C in the terminal to quit.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

    # Clean shutdown logic
    logger.info("Closing Application...")
    state.camera_active = False 
    sys.exit(0)

if __name__ == '__main__':
    start_desktop()
