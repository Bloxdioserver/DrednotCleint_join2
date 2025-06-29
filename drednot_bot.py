# drednot_bot.py (Version 4.0 - Proactive Joiner Bot)
# A standalone bot that waits in a default ship and joins a new one on command.
# All economy-related features have been removed for a focused purpose.

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
API_KEY = 'drednot123' # For on-demand join requests
ANONYMOUS_LOGIN_KEY = '' # Bot's primary login key
DEFAULT_SHIP_INVITE_LINK = 'https://drednot.io/invite/KOciB52Quo4z_luxo7zAFKPc' # The "waiting room" ship

MESSAGE_DELAY_SECONDS = 1.2
ZWSP = '\u200B'
INACTIVITY_TIMEOUT_SECONDS = 5 * 60 # Increased to 5 mins for less frequent rejoins
MAIN_LOOP_POLLING_INTERVAL_SECONDS = 1.5

# --- GLOBAL STATE ---
SHIP_TO_JOIN_URL = DEFAULT_SHIP_INVITE_LINK # The URL the bot will try to join on next restart
message_queue = queue.Queue(maxsize=20)
driver_lock = Lock()
inactivity_timer = None
driver = None
BOT_STATE = {"status": "Initializing...", "current_ship_id": "N/A", "last_join_request": "None yet.", "event_log": deque(maxlen=20)}

# --- JAVASCRIPT INJECTION (SIMPLIFIED) ---
# This script now ONLY looks for the "Joined ship" event.
MUTATION_OBSERVER_SCRIPT = """
    console.log('[Bot-JS] Initializing simplified MutationObserver...');
    window.py_bot_events = [];
    const targetNode = document.getElementById('chat-content');
    if (!targetNode) { return; }
    const callback = (mutationList, observer) => {
        for (const mutation of mutationList) {
            if (mutation.type === 'childList') {
                for (const node of mutation.addedNodes) {
                    if (node.nodeType !== 1 || node.tagName !== 'P') continue;
                    const pText = node.textContent || "";
                    if (pText.includes("Joined ship '")) {
                        const match = pText.match(/{[A-Z\\d]+}/);
                        if (match && match[0]) {
                            window.py_bot_events.push({ type: 'ship_joined', id: match[0] });
                        }
                    }
                }
            }
        }
    };
    const observer = new MutationObserver(callback);
    observer.observe(targetNode, { childList: true });
    console.log('[Bot-JS] Simplified MutationObserver is now active.');
"""

class InvalidKeyError(Exception): pass

def log_event(message):
    timestamp = datetime.now().strftime('%H:%M:%S')
    BOT_STATE["event_log"].appendleft(f"[{timestamp}] {message}")

# --- BROWSER SETUP ---
def find_chromium_executable():
    path = shutil.which('chromium') or shutil.which('chromium-browser')
    if path: return path
    raise FileNotFoundError("Could not find chromium or chromium-browser.")
def setup_driver():
    print("Launching headless browser with performance flags...")
    chrome_options = Options(); chrome_options.add_argument("--headless=new"); chrome_options.add_argument("--no-sandbox"); chrome_options.add_argument("--disable-dev-shm-usage"); chrome_options.add_argument("--disable-gpu"); chrome_options.add_argument("--disable-extensions"); chrome_options.add_argument("--mute-audio"); chrome_options.add_argument("--disable-images"); chrome_options.add_argument("--blink-settings=imagesEnabled=false"); chrome_options.binary_location = find_chromium_executable()
    return webdriver.Chrome(options=chrome_options)

# --- FLASK WEB SERVER ---
flask_app = Flask('')
@flask_app.route('/')
def health_check():
    html = f"""
    <!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="10">
    <title>Joiner Bot Status</title><style>body{{font-family:'Courier New',monospace;background-color:#1e1e1e;color:#d4d4d4;padding:20px;}}.container{{max-width:800px;margin:auto;background-color:#252526;border:1px solid #373737;padding:20px;border-radius:8px;}}h1{{color:#4ec9b0;}}p{{line-height:1.6;}}.status-ok{{color:#73c991;}}.status-warn{{color:#dccd85;}}.status-err{{color:#f44747;}}.label{{color:#9cdcfe;font-weight:bold;}}ul{{list-style-type:none;padding-left:0;}}li{{background-color:#2d2d2d;margin-bottom:8px;padding:10px;border-radius:4px;}}</style></head>
    <body><div class="container"><h1>Joiner Bot Status</h1>
    <p><span class="label">Status:</span> <span class="status-ok">{BOT_STATE['status']}</span></p>
    <p><span class="label">Current Ship ID:</span> {BOT_STATE['current_ship_id']}</p>
    <p><span class="label">Last Join Request:</span> {BOT_STATE['last_join_request']}</p>
    <h2>Recent Events</h2><ul>{''.join(f'<li>{event}</li>' for event in BOT_STATE['event_log'])}</ul></div></body></html>
    """
    return Response(html, mimetype='text/html')

def trigger_rejoin_to_new_ship(target_ship_id):
    global SHIP_TO_JOIN_URL, driver
    clean_ship_id = re.sub(r'[^a-zA-Z0-9{} ]', '', target_ship_id)
    new_url = f"https://drednot.io/s/{clean_ship_id}"
    with driver_lock:
        log_event(f"JOIN REQ: Received for {target_ship_id}."); print(f"[JOIN REQ] Received for {target_ship_id}.")
        BOT_STATE["last_join_request"] = f"{target_ship_id} at {datetime.now().strftime('%H:%M:%S')}"
        SHIP_TO_JOIN_URL = new_url
        BOT_STATE["status"] = f"Switching to ship {target_ship_id}..."
        if driver: driver.quit()

@flask_app.route('/join-request', methods=['POST'])
def handle_join_request():
    if request.headers.get('x-api-key') != API_KEY: return Response('{"error": "Invalid API key"}', status=401, mimetype='application/json')
    data = request.get_json();
    if not data or 'shipId' not in data: return Response('{"error": "Missing shipId"}', status=400, mimetype='application/json')
    threading.Thread(target=trigger_rejoin_to_new_ship, args=(data['shipId'],)).start()
    return Response('{"status": "Join request accepted, bot is restarting to join."}', status=200, mimetype='application/json')

def run_flask():
    port = int(os.environ.get("PORT", 8000)); print(f"Joiner Bot API listening on port {port}"); flask_app.run(host='0.0.0.0', port=port)

# --- HELPER & CORE FUNCTIONS ---
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
    inactivity_timer = threading.Timer(INACTIVITY_TIMEOUT_SECONDS, attempt_soft_rejoin)
    inactivity_timer.start()
def attempt_soft_rejoin():
    log_event("Game inactivity detected. Triggering restart to rejoin."); print(f"[REJOIN] No activity for {INACTIVITY_TIMEOUT_SECONDS}s. Triggering full restart.")
    global driver;
    if driver: driver.quit()

# --- MAIN BOT LOGIC ---
def start_bot(use_key_login):
    global driver
    BOT_STATE["status"] = "Launching Browser..."; log_event(f"Starting... Target: {SHIP_TO_JOIN_URL}")
    driver = setup_driver()
    with driver_lock:
        driver.get(SHIP_TO_JOIN_URL); print(f"Navigating to: {SHIP_TO_JOIN_URL}")
        wait = WebDriverWait(driver, 25)
        try:
            btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".modal-container .btn-green"))); driver.execute_script("arguments[0].click();", btn);
            if ANONYMOUS_LOGIN_KEY and use_key_login:
                link = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(., 'Restore old anonymous key')]"))); driver.execute_script("arguments[0].click();", link);
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'div.modal-window input[maxlength="24"]'))).send_keys(ANONYMOUS_LOGIN_KEY)
                submit_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//div[.//h2[text()='Restore Account Key']]//button[contains(@class, 'btn-green')]")));
                driver.execute_script("arguments[0].click();", submit_btn);
                wait.until(EC.invisibility_of_element_located((By.XPATH, "//div[.//h2[text()='Restore Account Key']]")))
                if driver.find_elements(By.XPATH, "//h2[text()='Login Failed']"): raise InvalidKeyError("Login Failed! Key may be invalid.")
            else:
                play_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Play Anonymously')]"))); driver.execute_script("arguments[0].click();", play_btn);
        except TimeoutException: print("Login prompts did not appear, assuming already in-game.")
        except Exception as e: log_event(f"Login failed critically: {e}"); raise e
        
        WebDriverWait(driver, 60).until(EC.presence_of_element_located((By.ID, "chat-input")));
        driver.execute_script(MUTATION_OBSERVER_SCRIPT); log_event("In-game, chat observer active.")
        
        found_id = driver.execute_script("for(const p of document.querySelectorAll('#chat-content p')){const t=p.textContent||'';if(t.includes(\"Joined ship '\")){const m=t.match(/{[A-Z\\d]+}/);if(m&&m[0])return m[0]}}return null;")
        if not found_id: raise RuntimeError("Failed to find Ship ID after joining.")

        BOT_STATE["current_ship_id"] = found_id; log_event(f"Confirmed in ship: {found_id}"); print(f"✅ Successfully joined ship: {found_id}")

    BOT_STATE["status"] = "Waiting for join command..."; queue_reply("Joiner bot is waiting."); reset_inactivity_timer()
    while True:
        try:
            with driver_lock: new_events = driver.execute_script("return window.py_bot_events.splice(0, window.py_bot_events.length);")
            if new_events:
                reset_inactivity_timer()
                for event in new_events:
                    if event['type'] == 'ship_joined' and event['id'] != BOT_STATE["current_ship_id"]:
                         BOT_STATE["current_ship_id"] = event['id']; log_event(f"Switched to new ship: {BOT_STATE['current_ship_id']}")
        except WebDriverException: raise
        time.sleep(MAIN_LOOP_POLLING_INTERVAL_SECONDS)

# --- MAIN EXECUTION ---
def run_bot_lifecycle():
    print("[SYSTEM] Delaying bot startup for 20 seconds to allow web server to stabilize...")
    time.sleep(20); print("[SYSTEM] Startup delay complete. Initializing bot lifecycle...")
    global SHIP_TO_JOIN_URL
    use_key_login = True; restart_count = 0; last_restart_time = time.time()
    while True:
        current_time = time.time()
        if current_time - last_restart_time < 3600: restart_count += 1
        else: restart_count = 1
        if restart_count > 10: print("CRITICAL: Bot is thrashing (restarting too quickly). Pausing for 5 minutes."); log_event("CRITICAL: Thrashing detected. Pausing."); time.sleep(300)
        
        try: start_bot(use_key_login)
        except InvalidKeyError as e:
            err_msg = f"CRITICAL: {e}. Switching to Guest Mode."; log_event(err_msg); print(f"[SYSTEM] {err_msg}"); use_key_login = False
        except Exception as e:
            BOT_STATE["status"] = "Crashed! Restarting..."; log_event(f"CRITICAL ERROR: {e}"); print(f"[SYSTEM] Full restart. Reason: {e}");
        finally:
            global driver;
            if inactivity_timer: inactivity_timer.cancel()
            if driver:
                try: driver.quit()
                except: pass
            driver = None
            if SHIP_TO_JOIN_URL != DEFAULT_SHIP_INVITE_LINK:
                print(f"[SYSTEM] Resetting next target URL to default: {DEFAULT_SHIP_INVITE_LINK}")
                SHIP_TO_JOIN_URL = DEFAULT_SHIP_INVITE_LINK
            time.sleep(5)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=message_processor_thread, daemon=True).start()
    bot_thread = threading.Thread(target=run_bot_lifecycle, daemon=True); bot_thread.start()
    bot_thread.join()
