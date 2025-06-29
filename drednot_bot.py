# drednot_bot.py (Version 6.0 - Optimized & Robust with Enhanced Login)
# A highly reliable, controllable bot with improved error handling, retry logic, and performance optimizations.

import os
import re
import time
import shutil
import queue
import threading
import traceback
from datetime import datetime
from collections import deque
from threading import Lock

from flask import Flask, Response, request
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import WebDriverException, TimeoutException

# --- CONFIGURATION ---
API_KEY = 'drednot123'
# Set this key to login with a restored anonymous account.
# Leave empty ('') to play as a new anonymous guest.
ANONYMOUS_LOGIN_KEY = '' # Example: '_M85tFxFxIRDax_nh-HYm1gT'
DEFAULT_SHIP_INVITE_LINK = 'https://drednot.io/invite/KOciB52Quo4z_luxo7zAFKPc'

MESSAGE_DELAY_SECONDS = 1.2
ZWSP = '\u200B'
INACTIVITY_TIMEOUT_SECONDS = 10 * 60 # 10 minutes

# --- JAVASCRIPT SNIPPETS ---
JS_CLICK_SCRIPT = "arguments[0].click();"
JS_FIND_AND_CLICK_SHIP = """
    const targetId = arguments[0];
    const idSpans = Array.from(document.querySelectorAll('.sy-id'));
    const targetSpan = idSpans.find(span => span.textContent === targetId);
    if (targetSpan) {
        const clickableDiv = targetSpan.parentElement;
        clickableDiv.click();
        return true; // Indicate success
    }
    return false; // Indicate failure
"""
JS_GET_SHIP_ID_FROM_CHAT = """
    for(const p of document.querySelectorAll('#chat-content p')) {
        const text = p.textContent || '';
        if (text.includes("Joined ship '")) {
            const match = text.match(/{[A-Z\\d]+}/);
            if (match && match[0]) return match[0];
        }
    }
    return null;
"""
MUTATION_OBSERVER_SCRIPT = """
    console.log('[Bot-JS] Initializing join event observer...');
    window.py_bot_events = []; const targetNode = document.getElementById('chat-content');
    if (!targetNode) return;
    const callback = (mutationList) => {
        for (const mutation of mutationList) {
            if (mutation.type === 'childList') {
                for (const node of mutation.addedNodes) {
                    if (node.nodeType !== 1 || node.tagName !== 'P') continue;
                    if ((node.textContent || "").includes("Joined ship '")) {
                        const match = node.textContent.match(/{[A-Z\\d]+}/);
                        if (match) window.py_bot_events.push({ type: 'ship_joined', id: match[0] });
                    }
                }
            }
        }
    };
    new MutationObserver(callback).observe(targetNode, { childList: true });
"""

# --- GLOBAL STATE ---
message_queue = queue.Queue(maxsize=20)
driver_lock = Lock()
inactivity_timer = None
driver = None
BOT_STATE = {"status": "Initializing...", "current_ship_id": "N/A", "last_command": "None yet.", "event_log": deque(maxlen=20)}

class InvalidKeyError(Exception): pass

# --- HELPER FUNCTIONS ---
def log_event(message):
    timestamp = datetime.now().strftime('%H:%M:%S')
    BOT_STATE["event_log"].appendleft(f"[{timestamp}] {message}")

def handle_critical_error(err_message, exception):
    """Centralized function for handling unrecoverable errors."""
    BOT_STATE["status"] = "Error! Restarting...";
    log_event(f"ERROR: {err_message} - {exception}")
    print(f"❌ [CRITICAL] {err_message}: {exception}")
    if driver:
        driver.quit() # Trigger the main loop's restart mechanism

# --- BROWSER SETUP ---
def find_chromium_executable():
    path = shutil.which('chromium') or shutil.which('chromium-browser')
    if path: return path
    raise FileNotFoundError("Could not find chromium or chromium-browser.")

def setup_driver():
    """Configures and launches a headless Chrome browser with performance optimizations."""
    print("Launching headless browser...")
    chrome_options = Options()
    # Performance & Stability Flags
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-background-networking")
    chrome_options.add_argument("--disable-sync")
    chrome_options.add_argument("--disable-images")
    chrome_options.add_argument("--blink-settings=imagesEnabled=false")
    # Resource Saving Flags
    chrome_options.add_argument("--mute-audio")
    chrome_options.add_argument("--single-process") # May help on low-resource machines

    try:
        chrome_options.binary_location = find_chromium_executable()
    except FileNotFoundError as e:
        print(f"FATAL: {e}"); exit(1)

    return webdriver.Chrome(options=chrome_options)

# --- FLASK WEB SERVER ---
flask_app = Flask('')
# ... (All Flask routes are unchanged) ...
@flask_app.route('/')
def health_check():
    html = f"""
    <!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="10">
    <title>Interactive Bot Status</title><style>body{{font-family:'Courier New',monospace;background-color:#1e1e1e;color:#d4d4d4;padding:20px;}}.container{{max-width:800px;margin:auto;background-color:#252526;border:1px solid #373737;padding:20px;border-radius:8px;}}h1{{color:#4ec9b0;}}p{{line-height:1.6;}}.status-ok{{color:#73c991;}}.status-warn{{color:#dccd85;}}.status-err{{color:#f44747;}}.label{{color:#9cdcfe;font-weight:bold;}}ul{{list-style-type:none;padding-left:0;}}li{{background-color:#2d2d2d;margin-bottom:8px;padding:10px;border-radius:4px;}}</style></head>
    <body><div class="container"><h1>Interactive Bot Status</h1>
    <p><span class="label">Status:</span> <span class="status-ok">{BOT_STATE['status']}</span></p>
    <p><span class="label">Current Ship ID:</span> {BOT_STATE['current_ship_id']}</p>
    <p><span class="label">Last Command:</span> {BOT_STATE['last_command']}</p>
    <h2>Recent Events</h2><ul>{''.join(f'<li>{event}</li>' for event in BOT_STATE['event_log'])}</ul></div></body></html>
    """
    return Response(html, mimetype='text/html')
@flask_app.route('/join-request', methods=['POST'])
def handle_join_request():
    if request.headers.get('x-api-key') != API_KEY: return Response('{"error": "Invalid API key"}', status=401)
    data = request.get_json();
    if not data or 'shipId' not in data: return Response('{"error": "Missing shipId"}', status=400)
    threading.Thread(target=perform_in_session_join, args=(data['shipId'],)).start()
    return Response('{"status": "Join request received."}', status=200)
@flask_app.route('/leave-request', methods=['POST'])
def handle_leave_request():
    if request.headers.get('x-api-key') != API_KEY: return Response('{"error": "Invalid API key"}', status=401)
    threading.Thread(target=perform_leave_ship).start()
    return Response('{"status": "Leave request received."}', status=200)
@flask_app.route('/say-request', methods=['POST'])
def handle_say_request():
    if request.headers.get('x-api-key') != API_KEY: return Response('{"error": "Invalid API key"}', status=401)
    data = request.get_json();
    if not data or 'message' not in data: return Response('{"error": "Missing message"}', status=400)
    queue_reply(data['message'])
    log_event(f"SAY REQ: Queued message: '{data['message']}'")
    BOT_STATE["last_command"] = f"!say {data['message'][:50]}"
    return Response('{"status": "Say request received."}', status=200)
def run_flask():
    port = int(os.environ.get("PORT", 8000)); print(f"Interactive Bot API listening on port {port}"); flask_app.run(host='0.0.0.0', port=port)

# --- CORE LOGIC ---
def queue_reply(message):
    try: message_queue.put(ZWSP + message, timeout=5)
    except queue.Full: print("[WARN] Message queue is full.")
def message_processor_thread():
    while True:
        message = message_queue.get()
        try:
            with driver_lock:
                if driver: driver.execute_script("const msg=arguments[0];const chatInp=document.getElementById('chat-input');const chatBtn=document.getElementById('chat-send');if(chatInp){chatInp.value=msg;}if(chatBtn){chatBtn.click();}", message)
        except WebDriverException: pass
        time.sleep(MESSAGE_DELAY_SECONDS)
def reset_inactivity_timer():
    global inactivity_timer
    if inactivity_timer: inactivity_timer.cancel()
    inactivity_timer = threading.Timer(INACTIVITY_TIMEOUT_SECONDS, lambda: driver.quit() if driver else None)
    inactivity_timer.start()

def perform_in_session_join(target_ship_id):
    """Performs the exit, refresh, and join sequence with robust retry logic."""
    with driver_lock:
        if not driver: log_event(f"ERROR: Join request for {target_ship_id}, but browser is offline."); return
        reset_inactivity_timer()
        log_event(f"JOIN: Starting sequence for {target_ship_id}."); print(f"[JOIN] Starting sequence for {target_ship_id}.")
        BOT_STATE["last_command"] = f"!join {target_ship_id}"

        try:
            wait = WebDriverWait(driver, 15)
            # Step 1: Exit
            BOT_STATE["status"] = "Exiting current ship..."; wait.until(EC.element_to_be_clickable((By.ID, "exit_button"))).click()
            wait.until(EC.presence_of_element_located((By.ID, 'shipyard'))); print("[JOIN] At main menu.")

            # Step 2: Find the ship with a retry loop
            for attempt in range(2): # Attempt to find the ship up to 2 times
                print(f"[JOIN] Refreshing ship list (Attempt {attempt + 1}/2)...")
                BOT_STATE["status"] = f"Refreshing list (Attempt {attempt + 1})..."
                wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Refresh')]"))).click()
                time.sleep(2.0) # Give a little more time for the list to populate

                if driver.execute_script(JS_FIND_AND_CLICK_SHIP, target_ship_id):
                    print(f"[JOIN] Found and clicked ship {target_ship_id} on attempt {attempt + 1}.")
                    # Step 3: Confirm join
                    wait.until(EC.presence_of_element_located((By.ID, 'chat-input')))
                    new_ship_id = driver.execute_script(JS_GET_SHIP_ID_FROM_CHAT)

                    BOT_STATE["current_ship_id"] = new_ship_id; BOT_STATE["status"] = f"In Ship: {new_ship_id}"
                    log_event(f"SUCCESS: Joined {new_ship_id}."); print(f"✅ [JOIN] Successfully joined {new_ship_id}!")
                    queue_reply(f"Bot has arrived.")
                    return # Exit the function on success

            # If the loop finishes without returning, it means we failed.
            raise RuntimeError(f"Could not find ship {target_ship_id} after 2 attempts.")

        except Exception as e:
            handle_critical_error("Join sequence failed", e)

def perform_leave_ship():
    with driver_lock:
        if not driver: log_event("ERROR: Leave request received, but browser is offline."); return
        reset_inactivity_timer()
        log_event("LEAVE: Starting leave sequence."); print("[LEAVE] Starting leave sequence.")
        BOT_STATE["last_command"] = "!leave"
        try:
            wait = WebDriverWait(driver, 5)
            BOT_STATE["status"] = "Leaving ship..."
            wait.until(EC.element_to_be_clickable((By.ID, "exit_button"))).click()
            wait.until(EC.presence_of_element_located((By.ID, 'shipyard')))
            BOT_STATE["status"] = "At Main Menu"; BOT_STATE["current_ship_id"] = "N/A"
            log_event("SUCCESS: Left ship."); print("✅ [LEAVE] Successfully left ship.")
        except TimeoutException:
            log_event("INFO: Leave ignored, already at main menu."); print("[LEAVE] Already at main menu.")
        except Exception as e:
            handle_critical_error("Leave sequence failed", e)

def start_bot():
    """Initializes the browser and waits in the default ship."""
    global driver
    BOT_STATE["status"] = "Launching Browser..."; log_event(f"Starting into waiting room: {DEFAULT_SHIP_INVITE_LINK}")
    driver = setup_driver()
    with driver_lock:
        driver.get(DEFAULT_SHIP_INVITE_LINK); print(f"Navigating to: {DEFAULT_SHIP_INVITE_LINK}")
        wait = WebDriverWait(driver, 30)
        def js_click(element): driver.execute_script(JS_CLICK_SCRIPT, element)
        try:
            accept_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//div[contains(@class, 'modal-container')]//button[contains(., 'Accept')]")))
            js_click(accept_button); print("[SETUP] Clicked 'Accept' on notice.")

            # --- NEW LOGIN LOGIC COPIED AND ADAPTED FROM SECOND SCRIPT ---
            if ANONYMOUS_LOGIN_KEY:
                log_event("Attempting login with key."); print("[SETUP] Attempting to log in with anonymous key.")
                link = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(., 'Restore old anonymous key')]")))
                js_click(link)
                print("[SETUP] Clicked 'Restore old anonymous key'.")

                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'div.modal-window input[maxlength="24"]'))).send_keys(ANONYMOUS_LOGIN_KEY)

                submit_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//div[.//h2[text()='Restore Account Key']]//button[contains(@class, 'btn-green')]")))
                js_click(submit_btn)
                print("[SETUP] Submitted key.")

                # Wait for EITHER the game to load (success) OR the login failed message to appear (failure)
                wait.until(EC.any_of(
                    EC.presence_of_element_located((By.ID, "chat-input")),
                    EC.presence_of_element_located((By.XPATH, "//h2[text()='Login Failed']"))
                ))

                # Now, check if the failure message is present, which indicates an invalid key
                if driver.find_elements(By.XPATH, "//h2[text()='Login Failed']"):
                    raise InvalidKeyError("Login Failed! Key may be invalid.")

                print("✅ [SETUP] Successfully logged in with key.")
                log_event("Login with key successful.")
            else:
                # This is the "guest login" part for when no key is provided
                log_event("Playing as new guest (no key provided).")
                play_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Play Anonymously')]")))
                js_click(play_button)
                print("[SETUP] Clicked 'Play Anonymously'.")
            # --- END OF NEW LOGIN LOGIC ---

        except Exception as e:
            log_event(f"Login failed critically: {e}"); raise e

        WebDriverWait(driver, 60).until(EC.presence_of_element_located((By.ID, "chat-input")))
        driver.execute_script(MUTATION_OBSERVER_SCRIPT); log_event("In-game, observer active.")

        # Using the robust Scan + Poll logic
        ship_id_found = False; print("[SETUP] Finding Ship ID...")
        found_id = driver.execute_script(JS_GET_SHIP_ID_FROM_CHAT)
        if found_id:
            ship_id_found = True
        else:
            start_time = time.time()
            while time.time() - start_time < 20:
                new_events = driver.execute_script("return window.py_bot_events.splice(0, window.py_bot_events.length);")
                if new_events: found_id = new_events[0]['id']; ship_id_found = True; break
                time.sleep(0.5)

        if not ship_id_found: raise RuntimeError("Failed to get Ship ID via scan or live event.")

        BOT_STATE["current_ship_id"] = found_id; log_event(f"Confirmed in waiting room: {found_id}"); print(f"✅ Successfully joined waiting room: {found_id}")

    BOT_STATE["status"] = "Waiting for command..."; queue_reply("Bot is waiting for commands.");
    while True:
        reset_inactivity_timer()
        time.sleep(60)

# --- MAIN EXECUTION BLOCK ---
def run_bot_lifecycle():
    print("[SYSTEM] Delaying bot startup for 20 seconds...")
    time.sleep(20); print("[SYSTEM] Startup delay complete. Initializing bot lifecycle.")
    restart_count = 0; last_restart_time = time.time()
    while True:
        current_time = time.time()
        if current_time - last_restart_time < 3600: restart_count += 1
        else: restart_count = 1
        if restart_count > 15: print("CRITICAL: Bot is thrashing. Pausing for 5 minutes."); log_event("CRITICAL: Thrashing detected. Pausing."); time.sleep(300)
        try:
            start_bot()
        except InvalidKeyError as e:
            # The new login logic can raise this error. The lifecycle loop will catch it and restart.
            # You could add special handling here, like disabling key login for future restarts.
            log_event(f"FATAL: {e}. Restarting...");
            print(f"FATAL: {e}. Restarting after a delay.")
            time.sleep(30) # Wait before restarting to avoid spamming a bad key
        except Exception as e:
            BOT_STATE["status"] = "Crashed! Restarting...";
            log_event(f"CRITICAL ERROR: {e}");
            print(f"[SYSTEM] Full restart. Reason: {e}");
        finally:
            global driver;
            if inactivity_timer: inactivity_timer.cancel()
            if driver:
                try: driver.quit()
                except: pass
            driver = None
            time.sleep(5)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=message_processor_thread, daemon=True).start()
    bot_thread = threading.Thread(target=run_bot_lifecycle, daemon=True); bot_thread.start()
    bot_thread.join()
