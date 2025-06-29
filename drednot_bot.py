# drednot_bot.py (Version 4.2 - In-Session Joining / Keyless)
# A standalone bot that waits in a default ship and performs a fast, in-session join on command.

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
# --- CHANGE: Key is now empty to force anonymous guest login ---
ANONYMOUS_LOGIN_KEY = ''
DEFAULT_SHIP_INVITE_LINK = 'https://drednot.io/invite/KOciB52Quo4z_luxo7zAFKPc'

MESSAGE_DELAY_SECONDS = 1.2
ZWSP = '\u200B'
INACTIVITY_TIMEOUT_SECONDS = 10 * 60 # 10 minutes

# --- GLOBAL STATE ---
message_queue = queue.Queue(maxsize=20)
driver_lock = Lock()
inactivity_timer = None
driver = None
BOT_STATE = {"status": "Initializing...", "current_ship_id": "N/A", "last_join_request": "None yet.", "event_log": deque(maxlen=20)}

class InvalidKeyError(Exception): pass

def log_event(message):
    timestamp = datetime.now().strftime('%H:%M:%S')
    BOT_STATE["event_log"].appendleft(f"[{timestamp}] {message}")

# --- BROWSER SETUP & FLASK ---
def find_chromium_executable():
    path = shutil.which('chromium') or shutil.which('chromium-browser')
    if path: return path
    raise FileNotFoundError("Could not find chromium or chromium-browser.")

def setup_driver():
    print("Launching headless browser...")
    chrome_options = Options(); chrome_options.add_argument("--headless=new"); chrome_options.add_argument("--no-sandbox"); chrome_options.add_argument("--disable-dev-shm-usage"); chrome_options.add_argument("--disable-gpu"); chrome_options.add_argument("--mute-audio"); chrome_options.add_argument("--disable-images"); chrome_options.add_argument("--blink-settings=imagesEnabled=false"); chrome_options.binary_location = find_chromium_executable()
    return webdriver.Chrome(options=chrome_options)

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

@flask_app.route('/join-request', methods=['POST'])
def handle_join_request():
    if request.headers.get('x-api-key') != API_KEY: return Response('{"error": "Invalid API key"}', status=401, mimetype='application/json')
    data = request.get_json();
    if not data or 'shipId' not in data: return Response('{"error": "Missing shipId"}', status=400, mimetype='application/json')
    threading.Thread(target=perform_in_session_join, args=(data['shipId'],)).start()
    return Response('{"status": "Join request received and is being processed."}', status=200, mimetype='application/json')

def run_flask():
    port = int(os.environ.get("PORT", 8000)); print(f"Joiner Bot API listening on port {port}"); flask_app.run(host='0.0.0.0', port=port)

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
    with driver_lock:
        if not driver:
            log_event(f"ERROR: Join request for {target_ship_id} received, but browser is not running.")
            return

        reset_inactivity_timer()
        log_event(f"JOIN REQ: Starting join sequence for {target_ship_id}.")
        print(f"[JOIN] Starting join sequence for {target_ship_id}.")
        BOT_STATE["last_join_request"] = f"{target_ship_id} at {datetime.now().strftime('%H:%M:%S')}"

        try:
            wait = WebDriverWait(driver, 15)
            BOT_STATE["status"] = "Exiting waiting room..."
            print("[JOIN] Step 1: Exiting current ship.")
            exit_button = wait.until(EC.element_to_be_clickable((By.ID, "exit_button")))
            driver.execute_script("arguments[0].click();", exit_button)
            
            wait.until(EC.presence_of_element_located((By.ID, 'shipyard')))
            print("[JOIN] Successfully returned to main menu.")

            BOT_STATE["status"] = "Refreshing ship list..."
            print("[JOIN] Step 2: Refreshing ship list.")
            refresh_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Refresh')]")))
            driver.execute_script("arguments[0].click();", refresh_button)
            time.sleep(1.5)

            BOT_STATE["status"] = f"Searching for {target_ship_id}..."
            print(f"[JOIN] Step 3: Searching for ship {target_ship_id}.")
            
            js_find_and_click = "const t=arguments[0];const s=Array.from(document.querySelectorAll('.sy-id')).find(e=>e.textContent===t);if(s){s.parentElement.click();return true}return false"
            was_clicked = driver.execute_script(js_find_and_click, target_ship_id)
            
            if not was_clicked:
                raise RuntimeError(f"Could not find ship {target_ship_id} in the list.")

            wait.until(EC.presence_of_element_located((By.ID, 'chat-input')))
            new_ship_id = driver.execute_script("for(const p of document.querySelectorAll('#chat-content p')){const t=p.textContent||'';if(t.includes(\"Joined ship '\")){const m=t.match(/{[A-Z\\d]+}/);if(m&&m[0])return m[0]}}return null;")
            
            BOT_STATE["current_ship_id"] = new_ship_id
            BOT_STATE["status"] = f"In Ship: {new_ship_id}"
            log_event(f"SUCCESS: Joined ship {new_ship_id}.")
            print(f"✅ [JOIN] Successfully joined ship {new_ship_id}!")
            queue_reply(f"Joiner bot has arrived.")

        except Exception as e:
            error_msg = f"Join sequence for {target_ship_id} failed: {e}"
            BOT_STATE["status"] = "Error during join"
            log_event(f"ERROR: {error_msg}")
            print(f"❌ [JOIN] {error_msg}")
            if driver: driver.quit()

def start_bot(use_key_login):
    global driver
    BOT_STATE["status"] = "Launching Browser..."; log_event(f"Starting into waiting room: {DEFAULT_SHIP_INVITE_LINK}")
    driver = setup_driver()
    with driver_lock:
        driver.get(DEFAULT_SHIP_INVITE_LINK); print(f"Navigating to: {DEFAULT_SHIP_INVITE_LINK}")
        wait = WebDriverWait(driver, 25)
        try:
            btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".modal-container .btn-green"))); driver.execute_script("arguments[0].click();", btn);
            if ANONYMOUS_LOGIN_KEY and use_key_login:
                print("[SETUP] Attempting to log in with anonymous key...")
                link = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(., 'Restore old anonymous key')]"))); driver.execute_script("arguments[0].click();", link);
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'div.modal-window input[maxlength="24"]'))).send_keys(ANONYMOUS_LOGIN_KEY)
                submit_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//div[.//h2[text()='Restore Account Key']]//button[contains(@class, 'btn-green')]")));
                driver.execute_script("arguments[0].click();", submit_btn);
                wait.until(EC.invisibility_of_element_located((By.XPATH, "//div[.//h2[text()='Restore Account Key']]")))
                if driver.find_elements(By.XPATH, "//h2[text()='Login Failed']"): raise InvalidKeyError("Login Failed! Key may be invalid.")
            else:
                print("[SETUP] No login key found. Playing as a new guest.")
                play_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Play Anonymously')]"))); driver.execute_script("arguments[0].click();", play_btn);
        except TimeoutException: print("[SETUP] Login prompts did not appear, assuming already in-game.")
        except Exception as e: log_event(f"Login failed critically: {e}"); raise e
        
        WebDriverWait(driver, 60).until(EC.presence_of_element_located((By.ID, "chat-input")));
        found_id = driver.execute_script("for(const p of document.querySelectorAll('#chat-content p')){const t=p.textContent||'';if(t.includes(\"Joined ship '\")){const m=t.match(/{[A-Z\\d]+}/);if(m&&m[0])return m[0]}}return null;")
        if not found_id: raise RuntimeError("Failed to find Ship ID after joining.")

        BOT_STATE["current_ship_id"] = found_id; log_event(f"Confirmed in waiting room: {found_id}"); print(f"✅ Successfully joined waiting room: {found_id}")

    BOT_STATE["status"] = "Waiting for join command..."; queue_reply("Joiner bot is waiting.");
    while True:
        reset_inactivity_timer()
        time.sleep(60)

def run_bot_lifecycle():
    print("[SYSTEM] Delaying bot startup for 20 seconds...")
    time.sleep(20); print("[SYSTEM] Startup delay complete. Initializing bot lifecycle.")
    use_key_login = True; restart_count = 0; last_restart_time = time.time()
    while True:
        current_time = time.time()
        if current_time - last_restart_time < 3600: restart_count += 1
        else: restart_count = 1
        if restart_count > 10: print("CRITICAL: Bot is thrashing. Pausing for 5 minutes."); log_event("CRITICAL: Thrashing detected. Pausing."); time.sleep(300)
        
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
            time.sleep(5)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=message_processor_thread, daemon=True).start()
    bot_thread = threading.Thread(target=run_bot_lifecycle, daemon=True); bot_thread.start()
    bot_thread.join()
