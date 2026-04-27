lucide.createIcons();

const container = document.getElementById('mainContainer');
const gesturePill = document.getElementById('gesturePill');
const gestureName = document.getElementById('gestureName');
const actionContainer = document.getElementById('actionContainer');
const actionText = document.getElementById('actionText');

let lastAction = "";
let actionTimer = null;
let isConnected = true;

function closeWindow() {
    if (window.pywebview && window.pywebview.api) {
        window.pywebview.api.toggle_floating_window();
    } else {
        window.close(); // Fallback for web
    }
}

async function updateStatus() {
    try {
        const res = await fetch('/api/status');
        if (!res.ok) throw new Error('Network response was not ok');
        const data = await res.json();

        isConnected = true;

        // 1. Gesture Tracking (Minimalist)
        const gesture = data.detected_gesture;
        const hasGesture = gesture && gesture !== "None";

        if (hasGesture) {
            container.classList.add('active');
            gesturePill.classList.remove('hidden');
            gestureName.innerText = gesture;
        } else {
            container.classList.remove('active');
            gesturePill.classList.add('hidden');
        }

        // 2. Action Feedback (Instant)
        if (data.last_action && data.last_action !== lastAction && data.last_action !== "None" && data.last_action !== "Tracking") {
            lastAction = data.last_action;

            actionText.innerText = data.last_action.replace(/_/g, ' ');
            actionContainer.classList.remove('hidden', 'translate-y-2', 'opacity-0');
            actionContainer.classList.add('translate-y-0', 'opacity-100');

            clearTimeout(actionTimer);
            actionTimer = setTimeout(() => {
                actionContainer.classList.add('translate-y-2', 'opacity-0');
                setTimeout(() => {
                    actionContainer.classList.add('hidden');
                }, 150);
                lastAction = ""; // Allow re-trigger
            }, 1500);
        }

    } catch (e) {
        if (isConnected) {
            isConnected = false;
        }
    }
}

// 3. Drag and Resize Logic
let isDragging = true;
let isResizing = true;
let startX, startY;
let startWidth, startHeight;
let windowX, windowY;

const dragRegion = document.querySelector('.drag-region');
const resizeHandle = document.getElementById('resizeHandle');

async function initWindowData(e) {
    if (window.pywebview && window.pywebview.api) {
        const pos = await window.pywebview.api.get_window_pos();
        if (pos) {
            windowX = pos.x;
            windowY = pos.y;
            startX = e.screenX;
            startY = e.screenY;
            return true;
        }
    }
    return false;
}

dragRegion.addEventListener('mousedown', async (e) => {
    // Prevent dragging if clicking on resize handle
    if (e.target === resizeHandle || resizeHandle.contains(e.target)) return;

    if (await initWindowData(e)) {
        isDragging = true;
        container.classList.add('dragging'); // Optional visual feedback
    }
});

resizeHandle.addEventListener('mousedown', async (e) => {
    isResizing = true;
    startX = e.screenX;
    startY = e.screenY;
    startWidth = window.innerWidth;
    startHeight = window.innerHeight;
    e.stopPropagation();
    e.preventDefault();
});

let lastCallTime = 0;
const THROTTLE_MS = 16; // ~60fps

window.addEventListener('mousemove', (e) => {
    const now = Date.now();
    if (now - lastCallTime < THROTTLE_MS) return;
    lastCallTime = now;

    if (isDragging && window.pywebview && window.pywebview.api) {
        const dx = e.screenX - startX;
        const dy = e.screenY - startY;

        // Update window position
        window.pywebview.api.move_window(windowX + dx, windowY + dy);
    }
    else if (isResizing && window.pywebview && window.pywebview.api) {
        const dx = e.screenX - startX;
        const dy = e.screenY - startY;

        const newW = Math.max(150, startWidth + dx);
        const newH = Math.max(100, startHeight + dy);

        window.pywebview.api.resize_window(newW, newH);
    }
});

window.addEventListener('mouseup', () => {
    isDragging = false;
    isResizing = false;
    container.classList.remove('dragging');
});

// Sync icons and status
window.addEventListener('pywebviewready', () => {
    console.log("Floating Window API Ready");
});

// Fast polling for responsive UI
setInterval(updateStatus, 50); // 50ms = 20fps updates
