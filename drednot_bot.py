# drednot_bot.py (Version 6.4 - High-Speed Join)
# Implements an "Optimistic Join" strategy to dramatically reduce ship joining times.

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
ANONYMOUS_LOGIN_KEY = '' # Set this key to login with a restored anonymous account.
DEFAULT_SHIP_INVITE_LINK = 'https://drednot.io/invite/KOciB52Quo4z_luxo7zAFKPc'

MESSAGE_DELAY_SECONDS = 1.2
ZWSP = '\u200B'
PROACTIVE_REJOIN_TIMEOUT_SECONDS = 2 * 60 # 2 minutes

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
rejoin_timer = None
driver = None
BOT_STATE = {"status": "Initializing...", "current_ship_id": "N/A", "last_command": "None yet.", "event_log": deque(maxlen=20)}

class InvalidKeyError(Exception): pass

# --- HELPER FUNCTIONS ---
def log_event(message):
    timestamp = datetime.now().strftime('%H:%M:%S')
    BOT_STATE["event_log"].appendleft(f"[{timestamp}] {message}")

def handle_critical_error(err_message, exception):
    BOT_STATE["status"] = "Error! Restarting...";
    log_event(f"ERROR: {err_message} - {exception}")
    print(f"❌ [CRITICAL] {err_message}: {exception}")
    if driver:
        driver.quit()

# --- BROWSER SETUP ---
# ... (Browser and Flask setup are unchanged) ...
def find_chromium_executable():
    path = shutil.which('chromium') or shutil.which('chromium-browser')
    if path: return path
    raise FileNotFoundError("Could not find chromium or chromium-browser.")

def setup_driver():
    print("Launching headless browser...")
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-background-networking")
    chrome_options.add_argument("--disable-sync")
    chrome_options.add_argument("--disable-images")
    chrome_options.add_argument("--blink-settings=imagesEnabled=false")
    chrome_options.add_argument("--mute-audio")
    chrome_options.add_argument("--single-process")
    try:
        chrome_options.binary_location = find_chromium_executable()
    except FileNotFoundError as e:
        print(f"FATAL: {e}"); exit(1)
    return webdriver.Chrome(options=chrome_options)
flask_app = Flask('')
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
    reset_proactive_rejoin_timer()
    if request.headers.get('x-api-key') != API_KEY: return Response('{"error": "Invalid API key"}', status=401)
    data = request.get_json();
    if not data or 'shipId' not in data: return Response('{"error": "Missing shipId"}', status=400)
    threading.Thread(target=perform_in_session_join, args=(data['shipId'],)).start()
    return Response('{"status": "Join request received."}', status=200)
@flask_app.route('/leave-request', methods=['POST'])
def handle_leave_request():
    reset_proactive_rejoin_timer()
    if request.headers.get('x-api-key') != API_KEY: return Response('{"error": "Invalid API key"}', status=401)
    threading.Thread(target=perform_leave_ship).start()
    return Response('{"status": "Leave request received."}', status=200)
@flask_app.route('/say-request', methods=['POST'])
def handle_say_request():
    reset_proactive_rejoin_timer()
    if request.headers.get('x-api-key') != API_KEY: return Response('{"error": "Invalid API key"}', status=401)
    data = request.get_json();
    if not data or 'message' not in data: return Response('{"error": "Missing message"}', status=400)
    queue_reply(data['message'])
    log_event(f"SAY REQ: Queued message: '{data['message']}'")
    BOT_STATE["last_command"] = f"!say {data['message'][:50]}"
    return Response('{"status": "Say request received."}', status=200)
def run_flask():
    port = int(os.environ.get("PORT", 8000)); print(f"Interactive Bot API listening on port {port}"); flask_app.run(host='0.0.0.0', port=port)

# --- CORE LOGIC & REJOIN MECHANISM ---
def reset_proactive_rejoin_timer():
    global rejoin_timer
    if rejoin_timer:
        rejoin_timer.cancel()
    rejoin_timer = threading.Timer(PROACTIVE_REJOIN_TIMEOUT_SECONDS, attempt_proactive_rejoin)
    rejoin_timer.start()

def attempt_proactive_rejoin():
    # ... (Proactive rejoin logic is unchanged) ...
    with driver_lock:
        if not driver: return
        ship_id_to_rejoin = BOT_STATE.get('current_ship_id')
        if not ship_id_to_rejoin or ship_id_to_rejoin == "N/A":
            log_event("REJOIN: Inactivity detected, but not in a ship. Skipping.")
            reset_proactive_rejoin_timer()
            return
        log_event(f"REJOIN: Inactivity detected. Attempting to rejoin {ship_id_to_rejoin}.")
        print(f"[REJOIN] No activity for {PROACTIVE_REJOIN_TIMEOUT_SECONDS}s. Attempting to rejoin {ship_id_to_rejoin}.")
        BOT_STATE["status"] = "Proactive Rejoin..."
        try:
            try:
                disconnect_button = WebDriverWait(driver, 2).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "#disconnect-popup button")))
                disconnect_button.click(); print("[REJOIN] Clicked disconnect pop-up button.")
            except TimeoutException:
                exit_button = WebDriverWait(driver, 2).until(EC.element_to_be_clickable((By.ID, "exit_button")))
                exit_button.click(); print("[REJOIN] Clicked exit button.")
            wait = WebDriverWait(driver, 10)
            wait.until(EC.presence_of_element_located((By.ID, 'shipyard')))
            print(f"[REJOIN] At main menu. Searching for {ship_id_to_rejoin}...")
            if not driver.execute_script(JS_FIND_AND_CLICK_SHIP, ship_id_to_rejoin):
                 raise RuntimeError(f"Could not find ship {ship_id_to_rejoin} in list after exiting.")
            wait.until(EC.presence_of_element_located((By.ID, 'chat-input')))
            BOT_STATE["status"] = f"In Ship: {ship_id_to_rejoin}"
            log_event(f"SUCCESS: Proactive rejoin to {ship_id_to_rejoin} successful.")
            print(f"✅ [REJOIN] Successfully rejoined {ship_id_to_rejoin}!")
            reset_proactive_rejoin_timer()
        except Exception as e:
            handle_critical_error(f"Proactive rejoin failed for ship {ship_id_to_rejoin}", e)

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

# --- HIGH-SPEED JOIN LOGIC ---
def perform_in_session_join(target_ship_id):
    with driver_lock:
        if not driver:
            log_event(f"ERROR: Join request for {target_ship_id}, but browser is offline.")
            return

        log_event(f"JOIN: Starting sequence for {target_ship_id}.")
        print(f"[JOIN] Starting sequence for {target_ship_id}.")
        BOT_STATE["last_command"] = f"!join {target_ship_id}"

        try:
            wait = WebDriverWait(driver, 10)
            BOT_STATE["status"] = "Exiting current ship..."
            wait.until(EC.element_to_be_clickable((By.ID, "exit_button"))).click()
            wait.until(EC.presence_of_element_located((By.ID, 'shipyard')))
            print("[JOIN] At main menu.")

            # --- NEW: OPTIMISTIC JOIN ATTEMPT (THE FAST PATH) ---
            print("[JOIN-OPT] Attempting optimistic join first...")
            if driver.execute_script(JS_FIND_AND_CLICK_SHIP, target_ship_id):
                print("[JOIN-OPT] Optimistic join SUCCESSFUL!")
                wait.until(EC.presence_of_element_located((By.ID, 'chat-input')))
                new_ship_id = driver.execute_script(JS_GET_SHIP_ID_FROM_CHAT)
                BOT_STATE["current_ship_id"] = new_ship_id
                BOT_STATE["status"] = f"In Ship: {new_ship_id}"
                log_event(f"SUCCESS: Joined {new_ship_id}.")
                print(f"✅ [JOIN] Successfully joined {new_ship_id}!")
                queue_reply(f"Bot has arrived.")
                return # Exit on success

            # --- FALLBACK: REFRESH AND RETRY (THE SLOW PATH) ---
            print("[JOIN-OPT] Optimistic join failed. Falling back to refresh-and-retry.")
            for attempt in range(2):
                print(f"[JOIN] Refreshing ship list (Attempt {attempt + 1}/2)...")
                BOT_STATE["status"] = f"Refreshing list (Attempt {attempt + 1})..."
                wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Refresh')]"))).click()
                time.sleep(1.0)
                if driver.execute_script(JS_FIND_AND_CLICK_SHIP, target_ship_id):
                    print(f"[JOIN] Found and clicked ship {target_ship_id} on attempt {attempt + 1}.")
                    wait.until(EC.presence_of_element_located((By.ID, 'chat-input')))
                    new_ship_id = driver.execute_script(JS_GET_SHIP_ID_FROM_CHAT)
                    BOT_STATE["current_ship_id"] = new_ship_id
                    BOT_STATE["status"] = f"In Ship: {new_ship_id}"
                    log_event(f"SUCCESS: Joined {new_ship_id}.")
                    print(f"✅ [JOIN] Successfully joined {new_ship_id}!")
                    queue_reply(f"Bot has arrived.")
                    return

            raise RuntimeError(f"Could not find ship {target_ship_id} after all attempts.")
        except Exception as e:
            handle_critical_error("Join sequence failed", e)

def perform_leave_ship():
    # ... (Leave logic is unchanged) ...
    with driver_lock:
        if not driver: log_event("ERROR: Leave request received, but browser is offline."); return
        log_event("LEAVE: Starting leave sequence."); print("[LEAVE] Starting leave sequence.")
        BOT_STATE["last_command"] = "!leave"
        try:
            wait = WebDriverWait(driver, 3)
            BOT_STATE["status"] = "Leaving ship..."
            wait.until(EC.element_to_be_clickable((By.ID, "exit_button"))).click()
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, 'shipyard')))
            BOT_STATE["status"] = "At Main Menu"; BOT_STATE["current_ship_id"] = "N/A"
            log_event("SUCCESS: Left ship."); print("✅ [LEAVE] Successfully left ship.")
        except TimeoutException:
            log_event("INFO: Leave ignored, already at main menu."); print("[LEAVE] Already at main menu.")
        except Exception as e:
            handle_critical_error("Leave sequence failed", e)

def start_bot():
    # ... (Start logic is unchanged) ...
    global driver
    BOT_STATE["status"] = "Launching Browser..."; log_event(f"Starting into waiting room: {DEFAULT_SHIP_INVITE_LINK}")
    driver = setup_driver()
    with driver_lock:
        driver.get(DEFAULT_SHIP_INVITE_LINK); print(f"Navigating to: {DEFAULT_SHIP_INVITE_LINK}")
        wait = WebDriverWait(driver, 20)
        def js_click(element): driver.execute_script(JS_CLICK_SCRIPT, element)
        try:
            accept_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//div[contains(@class, 'modal-container')]//button[contains(., 'Accept')]")))
            js_click(accept_button); print("[SETUP] Clicked 'Accept' on notice.")
            if ANONYMOUS_LOGIN_KEY:
                log_event("Attempting login with key."); print("[SETUP] Attempting to log in with anonymous key.")
                link = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(., 'Restore old anonymous key')]")))
                js_click(link); print("[SETUP] Clicked 'Restore old anonymous key'.")
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'div.modal-window input[maxlength="24"]'))).send_keys(ANONYMOUS_LOGIN_KEY)
                submit_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//div[.//h2[text()='Restore Account Key']]//button[contains(@class, 'btn-green')]")))
                js_click(submit_btn); print("[SETUP] Submitted key.")
                wait.until(EC.any_of(EC.presence_of_element_located((By.ID, "chat-input")),EC.presence_of_element_located((By.XPATH, "//h2[text()='Login Failed']"))))
                if driver.find_elements(By.XPATH, "//h2[text()='Login Failed']"): raise InvalidKeyError("Login Failed! Key may be invalid.")
                print("✅ [SETUP] Successfully logged in with key."); log_event("Login with key successful.")
            else:
                log_event("Playing as new guest (no key provided).")
                play_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Play Anonymously')]")));
                js_click(play_button)
                print("[SETUP] Clicked 'Play Anonymously'.")
        except Exception as e: log_event(f"Login failed critically: {e}"); raise e
        WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.ID, "chat-input")))
        driver.execute_script(MUTATION_OBSERVER_SCRIPT); log_event("In-game, observer active.")
        ship_id_found = False; print("[SETUP] Finding Ship ID...")
        found_id = driver.execute_script(JS_GET_SHIP_ID_FROM_CHAT)
        if found_id:
            ship_id_found = True
        else:
            start_time = time.time()
            while time.time() - start_time < 10:
                new_events = driver.execute_script("return window.py_bot_events.splice(0, window.py_bot_events.length);")
                if new_events: found_id = new_events[0]['id']; ship_id_found = True; break
                time.sleep(0.5)
        if not ship_id_found: raise RuntimeError("Failed to get Ship ID via scan or live event.")
        BOT_STATE["current_ship_id"] = found_id; log_event(f"Confirmed in waiting room: {found_id}"); print(f"✅ Successfully joined waiting room: {found_id}")
    BOT_STATE["status"] = "Waiting for command..."; queue_reply("Bot is waiting for commands.");
    reset_proactive_rejoin_timer()
    while True:
        time.sleep(60)

# --- MAIN EXECUTION BLOCK ---
def run_bot_lifecycle():
    # ... (Main loop is unchanged) ...
    print("[SYSTEM] Initializing bot lifecycle...")
    restart_count = 0; last_restart_time = time.time()
    while True:
        current_time = time.time()
        if current_time - last_restart_time < 3600: restart_count += 1
        else: restart_count = 1
        if restart_count > 15: print("CRITICAL: Bot is thrashing. Pausing for 5 minutes."); log_event("CRITICAL: Thrashing detected. Pausing."); time.sleep(300)
        try:
            start_bot()
        except InvalidKeyError as e:
            log_event(f"FATAL: {e}. Restarting..."); print(f"FATAL: {e}. Restarting after a delay.")
            time.sleep(30)
        except Exception as e:
            BOT_STATE["status"] = "Crashed! Restarting...";
            log_event(f"CRITICAL ERROR: {e}");
            print(f"[SYSTEM] Full restart. Reason: {e}");
        finally:
            global driver;
            if rejoin_timer:
                rejoin_timer.cancel()
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
