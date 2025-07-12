# drednot_bot.py
# FUSED DEFINITIVE VERSION
# This script uses the advanced Python framework (web UI, action queue, etc.)
# but has its Python-based rejoin logic replaced with the more robust and simple
# JavaScript-based auto-rejoin system.

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
BOT_SERVER_URL = os.environ.get("BOT_SERVER_URL")
API_KEY = 'drednot123'
SHIP_INVITE_LINK = 'https://drednot.io/invite/KOciB52Quo4z_luxo7zAFKPc'
ANONYMOUS_LOGIN_KEY = '_M85tFxFxIRDax_nh-HYm1gT'

# Bot Behavior
MESSAGE_DELAY_SECONDS = 0.2
ZWSP = '\u200B'
MAIN_LOOP_POLLING_INTERVAL_SECONDS = 0.05
MAX_WORKER_THREADS = 10

# Spam Control
USER_COOLDOWN_SECONDS = 2.0
SPAM_STRIKE_LIMIT = 3
SPAM_TIMEOUT_SECONDS = 30
SPAM_RESET_SECONDS = 5

# --- LOGGING & VALIDATION ---
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

if not BOT_SERVER_URL: logging.critical("FATAL: BOT_SERVER_URL environment variable is not set!"); exit(1)
if not SHIP_INVITE_LINK: logging.critical("FATAL: SHIP_INVITE_LINK environment variable is not set!"); exit(1)
if not API_KEY: logging.critical("FATAL: API_KEY environment variable is not set!"); exit(1)

# --- JAVASCRIPT INJECTION SCRIPT ---
# This new script combines the advanced command/spam listener with the simple auto-rejoin logic.
FUSED_CLIENT_SIDE_SCRIPT = """
(function() {
    'use strict';
    if (window.drednotBotFusedClient) { return; }
    window.drednotBotFusedClient = true;
    console.log('[Bot-JS Fused] Initializing client with command monitoring and auto-rejoin logic...');
    
    // --- Global Variables & Config ---
    window.py_bot_events = []; // Queue to send events back to Python
    const zwsp = arguments[0], allCommands = arguments[1], cooldownMs = arguments[2] * 1000,
          spamStrikeLimit = arguments[3], spamTimeoutMs = arguments[4] * 1000, spamResetMs = arguments[5] * 1000;
    const commandSet = new Set(allCommands);
    window.botUserCooldowns = window.botUserCooldowns || {};
    window.botSpamTracker = window.botSpamTracker || {};
    let chatObserver = null;
    let disconnectMonitorInterval = null;

    // --- Core Functions (Chat Monitor & Rejoin) ---
    const chatCallback = (mutationList, observer) => {
        const now = Date.now();
        for (const mutation of mutationList) {
            if (mutation.type !== 'childList') continue;
            for (const node of mutation.addedNodes) {
                if (node.nodeType !== 1 || node.tagName !== 'P' || node.dataset.botProcessed) continue;
                node.dataset.botProcessed = 'true';
                const pText = node.textContent || "";
                if (pText.startsWith(zwsp)) continue;
                if (pText.includes("Joined ship '")) {
                    const match = pText.match(/{[A-Z\\d]+}/);
                    if (match && match[0]) window.py_bot_events.push({ type: 'ship_joined', id: match[0] });
                    continue;
                }
                const colonIdx = pText.indexOf(':'); if (colonIdx === -1) continue;
                const bdiElement = node.querySelector("bdi"); if (!bdiElement) continue;
                const username = bdiElement.innerText.trim();
                const msgTxt = pText.substring(colonIdx + 1).trim();
                if (!msgTxt.startsWith('!')) continue;
                const parts = msgTxt.slice(1).trim().split(/ +/);
                const command = parts.shift().toLowerCase();
                if (!commandSet.has(command)) continue;
                const spamTracker = window.botSpamTracker[username] = window.botSpamTracker[username] || { count: 0, lastCmd: '', lastTime: 0, penaltyUntil: 0 };
                if (now < spamTracker.penaltyUntil) continue;
                const lastCmdTime = window.botUserCooldowns[username] || 0;
                if (now - lastCmdTime < cooldownMs) continue;
                window.botUserCooldowns[username] = now;
                if (now - spamTracker.lastTime > spamResetMs || command !== spamTracker.lastCmd) { spamTracker.count = 1; } else { spamTracker.count++; }
                spamTracker.lastCmd = command; spamTracker.lastTime = now;
                if (spamTracker.count >= spamStrikeLimit) {
                    spamTracker.penaltyUntil = now + spamTimeoutMs; spamTracker.count = 0;
                    window.py_bot_events.push({ type: 'spam_detected', username: username, command: command });
                    continue;
                }
                window.py_bot_events.push({ type: 'command', command: command, username: username, args: parts });
            }
        }
    };
    
    function startChatMonitor() {
        const targetNode = document.getElementById('chat-content');
        if (!targetNode) { console.error('[Bot-JS] Could not find chat content to observe.'); return; }
        chatObserver = new MutationObserver(chatCallback);
        chatObserver.observe(targetNode, { childList: true });
        console.log('[Bot-JS] Advanced command/spam monitor is now active.');
    }

    function handleRejoin() {
        console.log('[Bot-JS] Disconnect detected! Initiating automatic rejoin sequence.');
        if (disconnectMonitorInterval) clearInterval(disconnectMonitorInterval);
        if (chatObserver) chatObserver.disconnect();
        
        const returnButton = document.querySelector('div#disconnect-popup button.btn-green');
        if (returnButton) {
            returnButton.click();
            console.log('[Bot-JS] Clicked "Return to Menu". Waiting for menu screen...');
            const waitForMenu = setInterval(() => {
                if (document.querySelector("button.btn-large.btn-green[style*='display: block']")) {
                    clearInterval(waitForMenu);
                    console.log('[Bot-JS] Main menu detected. Reloading page to rejoin ship...');
                    location.reload();
                }
            }, 1000);
        } else {
            console.log('[Bot-JS] Could not find disconnect popup. Reloading page as a failsafe...');
            location.reload();
        }
    }

    function startDisconnectMonitor() {
        console.log('[Bot-JS] Starting disconnect monitor...');
        disconnectMonitorInterval = setInterval(() => {
            const disconnectPopup = document.querySelector('div#disconnect-popup');
            if (disconnectPopup && disconnectPopup.offsetParent !== null) {
                handleRejoin();
            }
        }, 5000);
    }

    // --- Main Initialization Logic ---
    function initialize() {
        const waitForGame = setInterval(() => {
            if (document.getElementById("chat-content")) {
                clearInterval(waitForGame);
                console.log('[Bot-JS] Game detected! Starting all monitors.');
                startChatMonitor();
                startDisconnectMonitor();
            }
        }, 500);
    }
    initialize();
})();
"""

class InvalidKeyError(Exception): pass

# --- GLOBAL STATE & THREADING PRIMITIVES ---
message_queue = queue.Queue(maxsize=100)
action_queue = queue.Queue(maxsize=10)
driver_lock = Lock()
driver = None # REMOVED: inactivity_timer
SERVER_COMMAND_LIST = []
BOT_STATE = {"status": "Initializing...", "start_time": datetime.now(), "current_ship_id": "N/A", "last_command_info": "None yet.", "last_message_sent": "None yet.", "event_log": deque(maxlen=20)}
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
    chrome_options.add_argument("--disable-infobars")
    chrome_options.add_argument("--mute-audio")
    chrome_options.add_argument("--disable-setuid-sandbox")
    chrome_options.add_argument("--disable-images")
    chrome_options.add_argument("--blink-settings=imagesEnabled=false")
    service = Service(executable_path="/usr/bin/chromedriver")
    return webdriver.Chrome(service=service, options=chrome_options)

flask_app = Flask('')
@flask_app.route('/')
def health_check():
    # Flask HTML is unchanged
    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="10"><title>Drednot Bot Status</title><style>body{{font-family:'Courier New',monospace;background-color:#1e1e1e;color:#d4d4d4;padding:20px;}}.container{{max-width:800px;margin:auto;background-color:#252526;border:1px solid #373737;padding:20px;border-radius:8px;}}h1,h2{{color:#4ec9b0;border-bottom:1px solid #4ec9b0;padding-bottom:5px;}}p{{line-height:1.6;}}.status-ok{{color:#73c991;font-weight:bold;}}.status-warn{{color:#dccd85;font-weight:bold;}}.status-err{{color:#f44747;font-weight:bold;}}ul{{list-style-type:none;padding-left:0;}}li{{background-color:#2d2d2d;margin-bottom:8px;padding:10px;border-radius:4px;white-space:pre-wrap;word-break:break-all;}}.label{{color:#9cdcfe;font-weight:bold;}}.btn{{background-color:#4ec9b0;color:#1e1e1e;border:none;padding:10px 15px;border-radius:4px;cursor:pointer;font-weight:bold;font-size:1em;margin-top:20px;}}.btn:hover{{background-color:#63d8c1;}}</style></head><body><div class="container"><h1>Drednot Bot Status</h1><p><span class="label">Status:</span><span class="status-ok">{BOT_STATE['status']}</span></p><p><span class="label">Current Ship ID:</span>{BOT_STATE['current_ship_id']}</p><p><span class="label">Last Command:</span>{BOT_STATE['last_command_info']}</p><p><span class="label">Last Message Sent:</span>{BOT_STATE['last_message_sent']}</p><form action="/update_commands" method="post"><button type="submit" class="btn">Refresh Commands Live</button></form><h2>Recent Events (Log)</h2><ul>{''.join(f'<li>{event}</li>' for event in BOT_STATE['event_log'])}</ul></div></body></html>"""
    return Response(html, mimetype='text/html')

@flask_app.route('/update_commands', methods=['POST'])
def trigger_command_update():
    # This function is unchanged
    log_event("WEB UI: Command update triggered.")
    def task():
        if fetch_command_list():
            queue_browser_update()
    command_executor.submit(task)
    return redirect(url_for('health_check'))

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    logging.info(f"Health check server listening on http://0.0.0.0:{port}")
    flask_app.run(host='0.0.0.0', port=port)

# --- HELPER & CORE FUNCTIONS ---
def queue_reply(message):
    # This function is unchanged
    MAX_LEN = 199
    lines = message if isinstance(message, list) else [message]
    for line in lines:
        text = str(line)
        while len(text) > 0:
            try:
                if len(text) <= MAX_LEN:
                    if text.strip(): message_queue.put(ZWSP + text, timeout=5)
                    break
                else:
                    bp = text.rfind(' ', 0, MAX_LEN)
                    chunk = text[:bp if bp > 0 else MAX_LEN].strip()
                    if chunk: message_queue.put(ZWSP + chunk, timeout=5)
                    text = text[bp if bp > 0 else MAX_LEN:].strip()
            except queue.Full:
                logging.warning("Message queue is full. Dropping message.")
                log_event("WARN: Message queue full.")
                break

def message_processor_thread():
    # This function is unchanged
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
def process_api_call(command, username, args):
    # This function is unchanged
    command_str = f"!{command} {' '.join(args)}"
    try:
        endpoint_url = urljoin(BOT_SERVER_URL, 'command')
        response = requests.post(endpoint_url, json={"command": command, "username": username, "args": args}, headers={"Content-Type": "application/json", "x-api-key": API_KEY}, timeout=15)
        response.raise_for_status()
        data = response.json()
        if data.get("reply"): queue_reply(data["reply"])
    except requests.exceptions.RequestException as e:
        logging.error(f"API call for '{command_str}' failed: {e}")
        queue_reply(f"@{username} Sorry, the economy server seems to be down.")
    except Exception as e: logging.error(f"Unexpected API error processing '{command_str}': {e}"); traceback.print_exc()

def process_commands_list_call(username):
    # This function is unchanged
    try:
        queue_reply(f"@{username} Fetching command list from server...")
        endpoint_url = urljoin(BOT_SERVER_URL, 'commands')
        response = requests.get(endpoint_url, headers={"x-api-key": API_KEY}, timeout=10)
        response.raise_for_status()
        command_list = response.json() 
        queue_reply("--- Available In-Game Commands ---")
        for cmd_string in command_list: queue_reply(cmd_string)
        queue_reply("------------------------------------")
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to fetch command list: {e}")
        queue_reply(f"@{username} Sorry, couldn't fetch the command list. The server might be down.")
    except Exception as e: logging.error(f"Unexpected error fetching command list: {e}"); traceback.print_exc()

# --- BOT MANAGEMENT FUNCTIONS ---

# REMOVED: The Python-based `attempt_soft_rejoin` function is no longer needed.
# REMOVED: The `reset_inactivity_timer` function is no longer needed.

def fetch_command_list():
    """Fetches command list from server and updates the global variable. Returns success."""
    # This function is unchanged
    global SERVER_COMMAND_LIST
    try:
        log_event("Fetching command list from server...")
        endpoint_url = urljoin(BOT_SERVER_URL, 'commands')
        response = requests.get(endpoint_url, headers={"x-api-key": API_KEY}, timeout=10)
        response.raise_for_status()
        full_command_strings = response.json()
        SERVER_COMMAND_LIST = [s.split(' ')[0][1:] for s in full_command_strings]
        SERVER_COMMAND_LIST.append('verify')
        log_event(f"Successfully processed {len(SERVER_COMMAND_LIST)} commands.")
        return True
    except Exception as e:
        log_event(f"CRITICAL: Failed to fetch command list: {e}")
        return False

def queue_browser_update():
    """Queues an action to re-inject the JS observer with the current command list."""
    # The action now injects the new FUSED script
    def update_action(driver_instance):
        log_event("Injecting/updating fused client-side script...")
        driver_instance.execute_script(
            FUSED_CLIENT_SIDE_SCRIPT, ZWSP, SERVER_COMMAND_LIST, USER_COOLDOWN_SECONDS, 
            SPAM_STRIKE_LIMIT, SPAM_TIMEOUT_SECONDS, SPAM_RESET_SECONDS
        )
        queue_reply("Commands have been updated live.")
    action_queue.put(update_action)

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
        # Login logic is unchanged
        try:
            btn = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".modal-container .btn-green")))
            driver.execute_script("arguments[0].click();", btn)
            logging.info("Clicked 'Accept' on notice.")
            if ANONYMOUS_LOGIN_KEY and use_key_login:
                # ... same key login logic ...
                log_event("Attempting login with hardcoded key.")
                link = wait.until(EC.presence_of_element_located((By.XPATH, "//a[contains(., 'Restore old anonymous key')]")))
                driver.execute_script("arguments[0].click();", link)
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'div.modal-window input[maxlength="24"]'))).send_keys(ANONYMOUS_LOGIN_KEY)
                submit_btn = wait.until(EC.presence_of_element_located((By.XPATH, "//div[.//h2[text()='Restore Account Key']]//button[contains(@class, 'btn-green')]")))
                driver.execute_script("arguments[0].click();", submit_btn)
                wait.until(EC.invisibility_of_element_located((By.XPATH, "//div[.//h2[text()='Restore Account Key']]")))
                wait.until(EC.any_of(EC.presence_of_element_located((By.ID, "chat-input")), EC.presence_of_element_located((By.XPATH, "//h2[text()='Login Failed']"))))
                if driver.find_elements(By.XPATH, "//h2[text()='Login Failed']"): raise InvalidKeyError("Login Failed! Key may be invalid.")
                log_event("✅ Successfully logged in with key.")
            else:
                log_event("Playing as new guest."); play_btn = wait.until(EC.presence_of_element_located((By.XPATH, "//button[contains(., 'Play Anonymously')]"))); driver.execute_script("arguments[0].click();", play_btn)
        except TimeoutException: log_event("Login timeout; assuming in-game.")
        except Exception as e: log_event(f"Login failed critically: {e}"); raise e

        WebDriverWait(driver, 60).until(EC.presence_of_element_located((By.ID, "chat-input")))
        if not fetch_command_list(): raise RuntimeError("Initial command fetch failed. Cannot start bot.")

        log_event("Injecting initial fused client script...")
        driver.execute_script(
            FUSED_CLIENT_SIDE_SCRIPT, ZWSP, SERVER_COMMAND_LIST, USER_COOLDOWN_SECONDS, 
            SPAM_STRIKE_LIMIT, SPAM_TIMEOUT_SECONDS, SPAM_RESET_SECONDS
        )

        # Proactive Ship ID scan is unchanged
        log_event("Proactively scanning for Ship ID...")
        PROACTIVE_SCAN_SCRIPT = """const chatContent = document.getElementById('chat-content'); if (!chatContent) { return null; } const paragraphs = chatContent.querySelectorAll('p'); for (const p of paragraphs) { const pText = p.textContent || ""; if (pText.includes("Joined ship '")) { const match = pText.match(/{[A-Z\\d]+}/); if (match && match[0]) { return match[0]; } } } return null;"""
        found_id = driver.execute_script(PROACTIVE_SCAN_SCRIPT)
        if found_id: BOT_STATE["current_ship_id"] = found_id; log_event(f"Confirmed Ship ID via scan: {found_id}")
        else:
            log_event("No existing ID found. Waiting for live event...")
            start_time = time.time(); ship_id_found = False
            while time.time() - start_time < 15:
                new_events = driver.execute_script("return window.py_bot_events.splice(0, window.py_bot_events.length);")
                for event in new_events:
                    if event['type'] == 'ship_joined': BOT_STATE["current_ship_id"] = event['id']; ship_id_found = True; log_event(f"Confirmed Ship ID via event: {BOT_STATE['current_ship_id']}"); break
                if ship_id_found: break; time.sleep(0.5)
            if not ship_id_found: error_message = "Failed to get Ship ID via scan or live event."; log_event(f"CRITICAL: {error_message}"); raise RuntimeError(error_message)

    BOT_STATE["status"] = "Running"
    queue_reply("Bot online. Auto-rejoin is active.")
    logging.info(f"Event-driven chat monitor active. Polling every {MAIN_LOOP_POLLING_INTERVAL_SECONDS}s.")
    
    while True:
        try:
            # Action queue logic is unchanged
            try:
                while not action_queue.empty():
                    action_to_run = action_queue.get_nowait()
                    with driver_lock:
                        if driver: action_to_run(driver) 
            except queue.Empty: pass

            with driver_lock:
                if not driver: break
                new_events = driver.execute_script("return window.py_bot_events.splice(0, window.py_bot_events.length);")
            
            if new_events:
                # REMOVED: No longer need to reset inactivity timer
                for event in new_events:
                    # Event processing logic is unchanged
                    if event['type'] == 'ship_joined' and event['id'] != BOT_STATE["current_ship_id"]:
                        BOT_STATE["current_ship_id"] = event['id']; log_event(f"Switched to new ship: {BOT_STATE['current_ship_id']}")
                    elif event['type'] == 'command':
                        cmd, user, args = event['command'], event['username'], event['args']; command_str = f"!{cmd} {' '.join(args)}"; logging.info(f"RECV: '{command_str}' from {user}"); BOT_STATE["last_command_info"] = f"{command_str} (from {user})"
                        if cmd == "commands": command_executor.submit(process_commands_list_call, user)
                        else: command_executor.submit(process_api_call, cmd, user, args)
                    elif event['type'] == 'spam_detected':
                        username, command = event['username'], event['command']; log_event(f"SPAM: Timed out '{username}' for {SPAM_TIMEOUT_SECONDS}s for spamming '!{command}'.")
        except WebDriverException as e:
            logging.error(f"WebDriver exception in main loop. Assuming disconnect: {e.msg}")
            raise
        time.sleep(MAIN_LOOP_POLLING_INTERVAL_SECONDS)

# --- MAIN EXECUTION ---
def main():
    # Main execution loop is unchanged, as its crash handling is already correct
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
            BOT_STATE["status"] = "Invalid Key!"; err_msg = f"CRITICAL: {e}. Switching to Guest Mode for next restart."; log_event(err_msg); logging.error(err_msg); use_key_login = False
        except Exception as e:
            BOT_STATE["status"] = "Crashed! Restarting..."; log_event(f"CRITICAL ERROR: {e}"); logging.critical(f"Full restart. Reason: {e}"); traceback.print_exc()
        finally:
            global driver
            # REMOVED: No inactivity_timer to cancel
            if driver:
                try: driver.quit()
                except: pass
            driver = None
            time.sleep(5)

if __name__ == "__main__":
    main()
