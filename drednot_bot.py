# drednot_bot.py
# FUSED VERSION: Kingdom Chat Client in the Economy Bot Framework
# This version uses the advanced Python backend (web UI, inactivity timer, programmatic rejoin)
# but injects a JavaScript client that communicates with the 'sortthechat.onrender.com' server,
# effectively making it a very robust client for your Kingdom Chat game.

import os
import queue
import atexit
import logging
import threading
import traceback
import requests
import time
from datetime import datetime
from collections import deque
from threading import Lock
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin 

from flask import Flask, Response, request, redirect, url_for
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import WebDriverException, TimeoutException

# --- CONFIGURATION ---
# The bot no longer needs to talk to the economy bot server, so this can be removed or ignored.
# BOT_SERVER_URL = os.environ.get("BOT_SERVER_URL") 
# API_KEY = 'drednot123'

SHIP_INVITE_LINK = 'https://drednot.io/invite/Wu5aTltskmcqkFP8rI0LW3Ws'
ANONYMOUS_LOGIN_KEY = '_M85tFxFxIRDax_nh-HYm1gT'

# Bot Behavior
MESSAGE_DELAY_SECONDS = 1.2 # Increased delay to be friendlier to the game chat
ZWSP = '\u200B'
INACTIVITY_TIMEOUT_SECONDS = 2 * 60 # The inactivity timer from your script is preserved
MAIN_LOOP_POLLING_INTERVAL_SECONDS = 0.05
MAX_WORKER_THREADS = 10 # This is no longer used for commands but kept for structure

# --- LOGGING & VALIDATION ---
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
if not SHIP_INVITE_LINK: logging.critical("FATAL: SHIP_INVITE_LINK environment variable is not set!"); exit(1)

# --- JAVASCRIPT INJECTION SCRIPT ---
# This is the new, self-contained JavaScript client for the Kingdom Chat server.
KINGDOM_CHAT_CLIENT_SCRIPT = """
(function() {
    'use strict';
    if (window.isKingdomClientInjected) { return; }
    window.isKingdomClientInjected = true;
    console.log('[Bot-JS] Initializing Kingdom Chat Client...');
    
    // --- State and Config ---
    window.py_bot_events = []; // Still used to send ship_joined events to Python
    const SERVER_URL = 'https://sortthechat.onrender.com/command';
    const MESSAGE_DELAY = 1200;
    const ZWSP = '\\u200B';
    let messageQueue = [];
    let isProcessingQueue = false;

    // --- Chat Sending Logic ---
    function sendChat(mess) {
        const chatBox = document.getElementById("chat");
        const chatInp = document.getElementById("chat-input");
        const chatBtn = document.getElementById("chat-send");
        if (chatBox?.classList.contains('closed')) chatBtn?.click();
        if (chatInp) chatInp.value = mess;
        chatBtn?.click();
    }
    function queueReply(message) {
        const MAX_LEN=199;
        const splitLongMessage=(line)=>{const c=[];let t=String(line);if(t.length<=MAX_LEN)return c.push(t),c;for(;t.length>0;){if(t.length<=MAX_LEN){c.push(t);break}let n=t.lastIndexOf(" ",MAX_LEN);n<=0&&(n=MAX_LEN),c.push(t.substring(0,n).trim()),t=t.substring(n).trim()}return c};
        (Array.isArray(message)?message:[message]).forEach(l=>{splitLongMessage(String(l)).forEach(c=>{c&&messageQueue.push(ZWSP+c)})});
        !isProcessingQueue&&processQueue();
    }
    function processQueue() {
        if(messageQueue.length===0){isProcessingQueue=false;return}
        isProcessingQueue=true;const nextMessage=messageQueue.shift();
        sendChat(nextMessage);setTimeout(processQueue,MESSAGE_DELAY);
    }

    // --- Main Observer Logic ---
    const observerCallback = (mutationList, observer) => {
        for (const mutation of mutationList) {
            if (mutation.type !== 'childList') continue;
            for (const node of mutation.addedNodes) {
                if (node.nodeType !== 1 || node.tagName !== 'P' || node.dataset.botProcessed) continue;
                node.dataset.botProcessed = 'true';
                const pText = node.textContent || "";
                if (pText.startsWith(ZWSP)) continue;
                
                // Keep the ship_joined event for Python's benefit
                if (pText.includes("Joined ship '")) {
                    const match = pText.match(/{[A-Z\\d]+}/);
                    if (match && match[0]) { window.py_bot_events.push({ type: 'ship_joined', id: match[0] }); }
                    continue;
                }
                
                const colonIdx = pText.indexOf(':'); if (colonIdx === -1) continue;
                const bdiElement = node.querySelector("bdi"); if (!bdiElement) continue;
                const playerName = bdiElement.innerText.trim();
                const commandText = pText.substring(colonIdx + 1).trim();
                const parts = commandText.split(' ');
                const command = parts[0];
                
                if (!command.startsWith('!')) continue;
                
                // Instead of sending to Python, this JS sends the command directly to the server
                console.log(`[Kingdom Chat] Sending command '${command}' for '${playerName}' to server.`);
                fetch(SERVER_URL, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    data: JSON.stringify({
                        playerName: playerName,
                        command: command,
                        args: parts.slice(1)
                    })
                })
                .then(response => response.json())
                .then(data => {
                    if (data.replies && Array.isArray(data.replies) && data.replies.length > 0) {
                        queueReply(data.replies); // Queue the server's reply to be typed out
                    }
                })
                .catch(error => {
                    console.error("[Kingdom Chat] Error sending command to server:", error);
                    queueReply("Error: Could not connect to the game server.");
                });
                
                // Push a generic event to Python just to reset the inactivity timer
                window.py_bot_events.push({ type: 'activity' });
            }
        }
    };
    
    const observer = new MutationObserver(observerCallback);
    const targetNode = document.getElementById('chat-content');
    if (targetNode) {
        observer.observe(targetNode, { childList: true });
        console.log('[Bot-JS] Kingdom Chat client is now active.');
    }
})();
"""

class InvalidKeyError(Exception): pass

# --- GLOBAL STATE & THREADING PRIMITIVES ---
message_queue = queue.Queue(maxsize=100) # Still used by the JS client indirectly via queue_reply
action_queue = queue.Queue(maxsize=10)
driver_lock = Lock()
inactivity_timer = None # This is the key component for the desired rejoin logic
driver = None
BOT_STATE = {"status": "Initializing...", "start_time": datetime.now(), "current_ship_id": "N/A", "last_command_info": "N/A", "last_message_sent": "None yet.", "event_log": deque(maxlen=20)}
command_executor = ThreadPoolExecutor(max_workers=MAX_WORKER_THREADS, thread_name_prefix='CmdWorker')
atexit.register(lambda: command_executor.shutdown(wait=True))

def log_event(message):
    timestamp = datetime.now().strftime('%H:%M:%S')
    full_message = f"[{timestamp}] {message}"
    BOT_STATE["event_log"].appendleft(full_message)
    logging.info(f"EVENT: {message}")

# --- BROWSER & FLASK SETUP ---
def setup_driver():
    logging.info("Launching headless browser for Docker environment...")
    chrome_options = Options()
    chrome_options.binary_location = "/usr/bin/chromium"
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--mute-audio")
    service = Service(executable_path="/usr/bin/chromedriver")
    return webdriver.Chrome(service=service, options=chrome_options)

flask_app = Flask('')
@flask_app.route('/')
def health_check():
    # Simplified the UI slightly by removing the "Refresh Commands" button
    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="10"><title>Drednot Bot Status</title><style>body{{font-family:'Courier New',monospace;background-color:#1e1e1e;color:#d4d4d4;padding:20px;}}.container{{max-width:800px;margin:auto;background-color:#252526;border:1px solid #373737;padding:20px;border-radius:8px;}}h1,h2{{color:#4ec9b0;border-bottom:1px solid #4ec9b0;padding-bottom:5px;}}p{{line-height:1.6;}}.status-ok{{color:#73c991;font-weight:bold;}}.label{{color:#9cdcfe;font-weight:bold;}}ul{{list-style-type:none;padding-left:0;}}li{{background-color:#2d2d2d;margin-bottom:8px;padding:10px;border-radius:4px;white-space:pre-wrap;word-break:break-all;}}</style></head><body><div class="container"><h1>Kingdom Chat Bot Status</h1><p><span class="label">Status:</span><span class="status-ok">{BOT_STATE['status']}</span></p><p><span class="label">Current Ship ID:</span>{BOT_STATE['current_ship_id']}</p><p><span class="label">Last Message Sent:</span>{BOT_STATE['last_message_sent']}</p><h2>Recent Events (Log)</h2><ul>{''.join(f'<li>{event}</li>' for event in BOT_STATE['event_log'])}</ul></div></body></html>"""
    return Response(html, mimetype='text/html')

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    logging.info(f"Health check server listening on http://0.0.0.0:{port}")
    flask_app.run(host='0.0.0.0', port=port)

# --- HELPER & CORE FUNCTIONS ---
def queue_reply_from_python(message):
    # This is a helper for Python to send messages, like "Bot online"
    try:
        if message.strip(): message_queue.put(ZWSP + message, timeout=5)
    except queue.Full:
        logging.warning("Message queue is full. Dropping python message.")

def message_processor_thread():
    # This thread is still needed for the JS `queueReply` to work, as it sends messages one by one
    while True:
        message = message_queue.get()
        try:
            with driver_lock:
                if driver:
                    driver.execute_script("const msg=arguments[0];const chatInp=document.getElementById('chat-input');const chatBtn=document.getElementById('chat-send');if(document.getElementById('chat')?.classList.contains('closed')){chatBtn.click();}if(chatInp){chatInp.value=msg;}chatBtn.click();", message)
            clean_msg = message[1:]
            logging.info(f"SENT: {clean_msg}")
            BOT_STATE["last_message_sent"] = clean_msg
        except WebDriverException: logging.warning("Message processor: WebDriver not available.")
        except Exception as e: logging.error(f"Unexpected error in message processor: {e}")
        time.sleep(MESSAGE_DELAY_SECONDS)

# --- COMMAND PROCESSING ---
# All Python-side command processing is removed, as the JS client now handles it.

# --- BOT MANAGEMENT FUNCTIONS ---
def reset_inactivity_timer():
    """This function is preserved entirely from your script."""
    global inactivity_timer
    if inactivity_timer: inactivity_timer.cancel()
    inactivity_timer = threading.Timer(INACTIVITY_TIMEOUT_SECONDS, attempt_soft_rejoin)
    inactivity_timer.start()

def attempt_soft_rejoin():
    """This is your desired auto-rejoin logic, preserved entirely."""
    log_event("Game inactivity detected. Attempting proactive rejoin.")
    BOT_STATE["status"] = "Proactive Rejoin..."
    global driver
    try:
        with driver_lock:
            ship_id = BOT_STATE.get('current_ship_id')
            if not ship_id or ship_id == 'N/A': raise ValueError("Cannot rejoin, no known Ship ID.")
            try: driver.find_element(By.CSS_SELECTOR, "#disconnect-popup button").click(); logging.info("Rejoin: Clicked disconnect pop-up.")
            except:
                try: driver.find_element(By.ID, "exit_button").click(); logging.info("Rejoin: Exiting ship normally.")
                except: logging.info("Rejoin: Not in game and no pop-up. Assuming at main menu.")
            wait = WebDriverWait(driver, 15)
            wait.until(EC.presence_of_element_located((By.ID, 'shipyard')))
            logging.info(f"Rejoin: At main menu. Searching for ship: {ship_id}")
            clicked = driver.execute_script("const sid=arguments[0];const s=Array.from(document.querySelectorAll('.sy-id')).find(e=>e.textContent===sid);if(s){s.click();return true}document.querySelector('#shipyard section:nth-of-type(3) .btn-small')?.click();return false", ship_id)
            if not clicked:
                time.sleep(0.5)
                clicked = driver.execute_script("const sid=arguments[0];const s=Array.from(document.querySelectorAll('.sy-id')).find(e=>e.textContent===sid);if(s){s.click();return true}return false", ship_id)
            if not clicked: raise RuntimeError(f"Could not find ship {ship_id} in list.")
            wait.until(EC.presence_of_element_located((By.ID, 'chat-input')))
            logging.info("✅ Proactive rejoin successful!")
            log_event("Proactive rejoin successful.")
            BOT_STATE["status"] = "Running"
            driver.execute_script(KINGDOM_CHAT_CLIENT_SCRIPT) # Re-inject the client after rejoin
            reset_inactivity_timer()
    except Exception as e:
        log_event(f"Rejoin FAILED: {e}")
        logging.error(f"Proactive rejoin failed: {e}. Triggering full restart.")
        if driver: driver.quit()

# --- MAIN BOT LOGIC ---
def start_bot(use_key_login):
    global driver
    BOT_STATE["status"] = "Launching Browser..."
    log_event("Performing full start...")
    driver = setup_driver()
    
    with driver_lock:
        logging.info(f"Navigating to invite link...")
        driver.get(SHIP_INVITE_LINK)
        wait = WebDriverWait(driver, 15)
        # Login logic is identical to your script
        try:
            btn = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".modal-container .btn-green")))
            driver.execute_script("arguments[0].click();", btn)
            logging.info("Clicked 'Accept' on notice.")
            if ANONYMOUS_LOGIN_KEY and use_key_login:
                log_event("Attempting login with hardcoded key."); link = wait.until(EC.presence_of_element_located((By.XPATH, "//a[contains(., 'Restore old anonymous key')]"))); driver.execute_script("arguments[0].click();", link); wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'div.modal-window input[maxlength="24"]'))).send_keys(ANONYMOUS_LOGIN_KEY); submit_btn = wait.until(EC.presence_of_element_located((By.XPATH, "//div[.//h2[text()='Restore Account Key']]//button[contains(@class, 'btn-green')]"))); driver.execute_script("arguments[0].click();", submit_btn); wait.until(EC.invisibility_of_element_located((By.XPATH, "//div[.//h2[text()='Restore Account Key']]"))); wait.until(EC.any_of(EC.presence_of_element_located((By.ID, "chat-input")), EC.presence_of_element_located((By.XPATH, "//h2[text()='Login Failed']"))));
                if driver.find_elements(By.XPATH, "//h2[text()='Login Failed']"): raise InvalidKeyError("Login Failed! Key may be invalid.")
                log_event("✅ Successfully logged in with key.")
            else:
                log_event("Playing as new guest."); play_btn = wait.until(EC.presence_of_element_located((By.XPATH, "//button[contains(., 'Play Anonymously')]"))); driver.execute_script("arguments[0].click();", play_btn)
        except TimeoutException: log_event("Login timeout; assuming in-game.")
        except Exception as e: log_event(f"Login failed critically: {e}"); raise e

        WebDriverWait(driver, 60).until(EC.presence_of_element_located((By.ID, "chat-input")))
        log_event("Injecting Kingdom Chat client script...")
        driver.execute_script(KINGDOM_CHAT_CLIENT_SCRIPT)

        # Proactive Ship ID scan logic is preserved
        log_event("Proactively scanning for Ship ID..."); PROACTIVE_SCAN_SCRIPT = """const c=document.getElementById('chat-content');if(!c)return null;const p=c.querySelectorAll('p');for(const a of p){const t=a.textContent||"";if(t.includes("Joined ship '")){const o=t.match(/{[A-Z\\d]+}/);if(o&&o[0])return o[0]}}return null;"""; found_id=driver.execute_script(PROACTIVE_SCAN_SCRIPT)
        if found_id: BOT_STATE["current_ship_id"] = found_id; log_event(f"Confirmed Ship ID via scan: {found_id}")
        else:
            log_event("No existing ID found. Waiting for live event..."); start_time=time.time();ship_id_found=False
            while time.time()-start_time<15:
                new_events=driver.execute_script("return window.py_bot_events.splice(0,window.py_bot_events.length);")
                for event in new_events:
                    if event['type']=='ship_joined':BOT_STATE["current_ship_id"]=event['id'];ship_id_found=True;log_event(f"Confirmed Ship ID via event: {BOT_STATE['current_ship_id']}");break
                if ship_id_found:break;time.sleep(0.5)
            if not ship_id_found:error_message="Failed to get Ship ID.";log_event(f"CRITICAL: {error_message}");raise RuntimeError(error_message)

    BOT_STATE["status"] = "Running"
    queue_reply_from_python("👑 Kingdom Chat bot online.")
    reset_inactivity_timer() # Start the inactivity timer
    logging.info(f"Kingdom Chat client active. Polling every {MAIN_LOOP_POLLING_INTERVAL_SECONDS}s.")
    
    while True:
        try:
            with driver_lock:
                if not driver: break
                new_events = driver.execute_script("return window.py_bot_events.splice(0, window.py_bot_events.length);")
            
            if new_events:
                reset_inactivity_timer() # Any activity from the browser resets the timer
                for event in new_events:
                    if event['type'] == 'ship_joined' and event['id'] != BOT_STATE["current_ship_id"]:
                        BOT_STATE["current_ship_id"] = event['id']
                        log_event(f"Switched to new ship: {BOT_STATE['current_ship_id']}")
                    # No longer need to process commands here, JS does it.
                    # We only care that *an* event happened.
                        
        except WebDriverException as e:
            logging.error(f"WebDriver exception in main loop. Assuming disconnect: {e.msg}")
            raise
        time.sleep(MAIN_LOOP_POLLING_INTERVAL_SECONDS)

# --- MAIN EXECUTION ---
def main():
    # This is your robust main execution loop, preserved entirely.
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=message_processor_thread, daemon=True).start()
    use_key_login = True; restart_count = 0; last_restart_time = time.time()
    while True:
        current_time = time.time()
        if current_time - last_restart_time < 3600: restart_count += 1
        else: restart_count = 1
        last_restart_time = current_time
        if restart_count > 10: log_event("CRITICAL: Bot is thrashing. Pausing for 5 minutes."); logging.critical("BOT RESTARTED >10 TIMES/HOUR. PAUSING FOR 5 MINS."); time.sleep(300)
        try:
            start_bot(use_key_login)
        except InvalidKeyError as e:
            BOT_STATE["status"] = "Invalid Key!"; err_msg = f"CRITICAL: {e}. Switching to Guest Mode."; log_event(err_msg); logging.error(err_msg); use_key_login = False
        except Exception as e:
            BOT_STATE["status"] = "Crashed! Restarting..."; log_event(f"CRITICAL ERROR: {e}"); logging.critical(f"Full restart. Reason: {e}"); traceback.print_exc()
        finally:
            global driver
            if inactivity_timer: inactivity_timer.cancel()
            if driver:
                try: driver.quit()
                except: pass
            driver = None
            time.sleep(5)

if __name__ == "__main__":
    main()
