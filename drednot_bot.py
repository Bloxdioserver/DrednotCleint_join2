# FUSED DEFINITIVE VERSION - REJOIN ENHANCED
# This script combines the "Kingdom" bot's purpose with the "EconomyBot's"
# superior auto-rejoin and monitoring logic. It uses a proactive
# inactivity timer and Ship ID tracking for maximum resilience.

import os
import logging
import threading
import traceback
import time
from datetime import datetime
from collections import deque

from flask import Flask, Response
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import WebDriverException, TimeoutException

# --- CONFIGURATION ---
SHIP_INVITE_LINK = "https://drednot.io/invite/Wu5aTltskmcqkFP8rI0LW3Ws"
ANONYMOUS_LOGIN_KEY = "_M85tFxFxIRDax_nh-HYm1gT"
MAX_FAILURES = 5 # Increased for more resilience

# --- NEW: Rejoin & Monitoring Configuration ---
INACTIVITY_TIMEOUT_SECONDS = 3 * 60 # 3 minutes
MAIN_LOOP_POLLING_INTERVAL_SECONDS = 1.0 # Check for activity every second

# --- LOGGING & VALIDATION ---
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

if not SHIP_INVITE_LINK:
    logging.critical("FATAL: SHIP_INVITE_LINK environment variable is not set!")
    exit(1)

# --- JAVASCRIPT PAYLOADS ---

# SCRIPT 1: Unchanged. Injected into a blank page to neuter the browser BEFORE the game loads.
PERFORMANCE_BOOSTER_SCRIPT = """
console.log('[PerfBooster] Applying aggressive optimizations...');
window.requestAnimationFrame = () => {}; window.cancelAnimationFrame = () => {};
window.AudioContext = undefined; window.webkitAudioContext = undefined;
window.createImageBitmap = () => Promise.reject(new Error('Disabled for performance'));
const style = document.createElement('style');
style.innerHTML = `canvas, .game-background { display: none !important; }`;
document.head.appendChild(style);
console.log('[PerfBooster] Game rendering, audio, and heavy elements neutralized.');
"""

# SCRIPT 2: The client script, now modified to support the new rejoin logic.
# - REMOVED: handleRejoin, startDisconnectMonitor, stopAllMonitors
# - ADDED: window.py_bot_events array to communicate with Python.
# - ADDED: Logic to detect Ship ID and push 'command_processed' events for heartbeat.
CLIENT_SIDE_SCRIPT = """
(function() {
    'use strict';
    if (window.kingdomChatClientLoaded) { return; }
    window.kingdomChatClientLoaded = true;
    // NEW: Event queue for Python to monitor activity.
    if (!window.py_bot_events) { window.py_bot_events = []; }
    console.log('[Kingdom Chat] Initializing client with enhanced monitoring...');

    const SERVER_URL = 'https://sortthechat.onrender.com/command';
    const MESSAGE_DELAY = 1200;
    const ZWSP = '\\u200B';
    let messageQueue = [];
    let isProcessingQueue = false;
    let chatObserver = null;

    function sendChat(mess) { /* ... (This function is unchanged) ... */ }
    function queueReply(message) { /* ... (This function is unchanged) ... */ }
    function processQueue() { /* ... (This function is unchanged) ... */ }
    
    function startChatMonitor() {
        if (chatObserver) return;
        console.log("[Kingdom Chat] Starting chat command monitor...");
        const chatContent = document.getElementById("chat-content"); if (!chatContent) return;
        chatObserver = new MutationObserver(mutations => {
            mutations.forEach(mutation => {
                mutation.addedNodes.forEach(node => {
                    if (node.nodeType !== 1 || node.tagName !== "P") return;
                    const pTextContent = node.textContent || "";
                    if (pTextContent.startsWith(ZWSP)) return;

                    // NEW: Listen for "Joined ship" message to get the Ship ID
                    if (pTextContent.includes("Joined ship '")) {
                        const match = pTextContent.match(/{[A-Z\\d]+}/);
                        if (match && match[0]) {
                            window.py_bot_events.push({ type: 'ship_joined', id: match[0] });
                        }
                        return; // Don't process this message for commands
                    }
                    
                    const bdiMatch = node.innerHTML.match(/<bdi.*?>(.*?)<\\/bdi>/); if (!bdiMatch) return;
                    const playerName = bdiMatch[1].trim(); const colonIdx = pTextContent.indexOf(':'); if (colonIdx === -1) return;
                    const command = pTextContent.substring(colonIdx + 1).trim().split(' ')[0]; if (!command.startsWith('!')) return;
                    
                    // NEW: Push an event to Python to act as a "heartbeat"
                    window.py_bot_events.push({ type: 'command_processed' });

                    const args = pTextContent.substring(colonIdx + 1).trim().split(' ').slice(1);
                    fetch(SERVER_URL, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ playerName, command, args })
                    }).then(r => r.json()).then(d => { if (d.replies && d.replies.length > 0) queueReply(d.replies); }).catch(e => console.error("KC Error:", e));
                });
            });
        });
        chatObserver.observe(chatContent, { childList: true });
    }

    const waitForGame = setInterval(() => {
        if (document.getElementById("chat-content")) {
            clearInterval(waitForGame);
            console.log('[Kingdom Chat] Game detected!');
            queueReply("👑 Kingdom Chat Client connected. Enhanced auto-rejoin is active.");
            startChatMonitor();
        }
    }, 500);
})();
"""

# --- GLOBAL STATE & NEW THREADING PRIMITIVES ---
driver = None
inactivity_timer = None # NEW: For tracking inactivity
BOT_STATE = {"status": "Initializing...", "start_time": datetime.now(), "current_ship_id": "N/A", "event_log": deque(maxlen=20)}

def log_event(message):
    timestamp = datetime.now().strftime('%H:%M:%S')
    full_message = f"[{timestamp}] {message}"
    BOT_STATE["event_log"].appendleft(full_message)
    logging.info(f"EVENT: {message}")

# --- BROWSER & FLASK SETUP (Unchanged) ---
def setup_driver():
    # ... (This function is unchanged from the original Kingdom bot) ...
    logging.info("Launching headless browser with STABILITY-focused performance options...")
    chrome_options = Options()
    chrome_options.binary_location = "/usr/bin/chromium"
    chrome_options.add_argument("--headless=new") # ... etc.
    return webdriver.Chrome(options=chrome_options)

flask_app = Flask('')
@flask_app.route('/')
def health_check():
    # ... (This function is unchanged from the original Kingdom bot) ...
    uptime = str(datetime.now() - BOT_STATE['start_time']).split('.')[0]
    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="10"><title>Bot Status</title><style>body{{font-family:monospace;background-color:#1e1e1e;color:#d4d4d4;}}</style></head><body><h1>Selenium Bridge Bot Status</h1><p><b>Status:</b> {BOT_STATE['status']}</p><p><b>Ship ID:</b> {BOT_STATE['current_ship_id']}</p><p><b>Uptime:</b> {uptime}</p><h2>Event Log</h2><pre>{'<br>'.join(BOT_STATE['event_log'])}</pre></body></html>"""
    return Response(html, mimetype='text/html')

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    logging.info(f"Health check server listening on http://0.0.0.0:{port}")
    flask_app.run(host='0.0.0.0', port=port)

# --- NEW: Rejoin Logic Transplanted from EconomyBot ---
def reset_inactivity_timer():
    """Cancels the old timer and starts a new one."""
    global inactivity_timer
    if inactivity_timer:
        inactivity_timer.cancel()
    inactivity_timer = threading.Timer(INACTIVITY_TIMEOUT_SECONDS, attempt_soft_rejoin)
    inactivity_timer.start()

def attempt_soft_rejoin():
    """Proactively tries to rejoin the ship without a full browser restart."""
    log_event("Game inactivity detected. Attempting proactive soft rejoin.")
    BOT_STATE["status"] = "Attempting Soft Rejoin..."
    global driver
    if not driver:
        log_event("Soft rejoin failed: Driver is not alive.")
        return

    try:
        ship_id = BOT_STATE.get('current_ship_id')
        if not ship_id or ship_id == 'N/A':
            raise ValueError("Cannot rejoin, no known Ship ID.")

        # Try to find and click the disconnect popup first
        try:
            driver.find_element(By.CSS_SELECTOR, "div#disconnect-popup button.btn-green").click()
            log_event("Rejoin: Clicked disconnect pop-up.")
        except Exception:
            # If no popup, try to exit normally
            try:
                driver.find_element(By.ID, "exit_button").click()
                log_event("Rejoin: Exiting ship via exit button.")
            except Exception:
                log_event("Rejoin: No pop-up or exit button. Assuming at main menu.")

        # Now at main menu, find the ship by ID
        wait = WebDriverWait(driver, 20)
        wait.until(EC.presence_of_element_located((By.ID, 'shipyard')))
        log_event(f"Rejoin: At main menu. Searching for ship: {ship_id}")
        
        # This JS snippet finds the ship ID in the server list and clicks it.
        clicked = driver.execute_script("""
            const sid = arguments[0];
            const ship_element = Array.from(document.querySelectorAll('.sy-id')).find(e => e.textContent === sid);
            if (ship_element) {
                ship_element.click();
                return true;
            }
            return false;
        """, ship_id)
        
        if not clicked:
            raise RuntimeError(f"Could not find ship {ship_id} in the server list.")
        
        # Wait until we are back in the game
        wait.until(EC.presence_of_element_located((By.ID, 'chat-input')))
        log_event("✅ Soft rejoin successful!")
        BOT_STATE["status"] = "Running"
        reset_inactivity_timer() # Start the timer again now that we're back
    except Exception as e:
        log_event(f"Soft rejoin FAILED: {e}. Triggering full hard restart.")
        # Quit the driver. The main loop's finally block will catch this and restart.
        if driver:
            driver.quit()

# --- BOT STARTUP LOGIC ---
def start_bot(use_key_login):
    global driver
    BOT_STATE["status"] = "Launching Browser..."
    log_event("Starting new Selenium session...")
    driver = setup_driver()

    # ... (The pre-emptive script injection part is unchanged) ...
    log_event("Loading blank page for pre-emptive script injection...")
    driver.get("about:blank")
    log_event("Injecting performance booster before navigating to game...")
    driver.execute_script(PERFORMANCE_BOOSTER_SCRIPT)

    log_event(f"Navigating to invite link...")
    driver.get(SHIP_INVITE_LINK)

    # ... (The login logic is unchanged from the original Kingdom bot) ...
    try:
        # ... (Identical login logic as the original script) ...
    except Exception as e:
        log_event(f"Critical error during login: {e}")
        raise

    log_event("Waiting for page to load before injecting client...")
    WebDriverWait(driver, 60).until(EC.presence_of_element_located((By.ID, "chat-input")))
    log_event("Game loaded.")

    log_event("Injecting full JavaScript client into the page...")
    driver.execute_script(CLIENT_SIDE_SCRIPT)
    log_event("JavaScript client injected successfully.")

    # --- NEW: Find and confirm the Ship ID ---
    log_event("Attempting to get Ship ID...")
    start_time = time.time()
    ship_id_found = False
    while time.time() - start_time < 20: # Wait up to 20 seconds for the ID
        try:
            new_events = driver.execute_script("return window.py_bot_events.splice(0, window.py_bot_events.length);")
            for event in new_events:
                if event.get('type') == 'ship_joined':
                    BOT_STATE["current_ship_id"] = event['id']
                    ship_id_found = True
                    log_event(f"✅ Confirmed Ship ID: {BOT_STATE['current_ship_id']}")
                    break
            if ship_id_found:
                break
        except WebDriverException:
            # Browser might have closed, break loop to trigger restart
            break
        time.sleep(1)
    
    if not ship_id_found:
        raise RuntimeError("Failed to get Ship ID after joining. Cannot guarantee rejoin.")


# --- MAIN EXECUTION & LIFECYCLE MANAGEMENT ---
# This is the new, more robust main loop.
def main():
    threading.Thread(target=run_flask, daemon=True).start()
    use_key_login = True
    failure_count = 0

    while failure_count < MAX_FAILURES:
        try:
            start_bot(use_key_login)
            log_event("Bot is running. Python is now monitoring game activity.")
            BOT_STATE["status"] = "Running (Monitoring JS client)"
            failure_count = 0 
            reset_inactivity_timer() # Start the timer for the first time

            # This is the new monitoring loop. It checks for JS activity.
            while True:
                time.sleep(MAIN_LOOP_POLLING_INTERVAL_SECONDS)
                
                # Get events from JS (chat commands, etc.)
                new_events = driver.execute_script("return window.py_bot_events.splice(0, window.py_bot_events.length);")
                
                if new_events:
                    # Any activity from the JS side resets the inactivity timer.
                    reset_inactivity_timer()
                    
                    # Also check if we've somehow joined a new ship
                    for event in new_events:
                        if event.get('type') == 'ship_joined' and event.get('id') != BOT_STATE["current_ship_id"]:
                            log_event(f"Detected switch to new ship: {event['id']}")
                            BOT_STATE["current_ship_id"] = event['id']
                
                # This simple check ensures the browser process hasn't died completely.
                # If it has, it raises a WebDriverException, triggering the hard restart.
                _ = driver.window_handles 

        except WebDriverException as e:
            # This catches browser crashes or if driver.quit() was called in soft_rejoin
            failure_count += 1
            BOT_STATE["status"] = f"Browser Unresponsive! Restarting... (Failure {failure_count}/{MAX_FAILURES})"
            log_event(f"WebDriver Exception (Failure #{failure_count}): {e.msg.splitlines()[0]}")

        except Exception as e:
            failure_count += 1
            BOT_STATE["status"] = f"Crashed! Restarting... (Failure {failure_count}/{MAX_FAILURES})"
            log_event(f"CRITICAL ERROR (Failure #{failure_count}): {e}")
            traceback.print_exc()

            if "invalid" in str(e).lower():
                log_event("Login key may be invalid. Will try as Guest on next restart.")
                use_key_login = False
        finally:
            if inactivity_timer:
                inactivity_timer.cancel()
            if driver:
                try: driver.quit()
                except Exception: pass
                driver = None

            if failure_count < MAX_FAILURES:
                log_event(f"Waiting 10 seconds before restart...")
                time.sleep(10)
            else:
                log_event(f"FATAL: Reached {MAX_FAILURES} consecutive failures. Bot is stopping.")
                BOT_STATE["status"] = f"STOPPED after {MAX_FAILURES} failures."
                logging.critical("Bot has been shut down permanently due to repeated errors.")
                break # Exit the while loop

if __name__ == "__main__":
    main()
