# FUSED DEFINITIVE VERSION - MEMORY & STABILITY ENHANCED
# This script incorporates all previous enhancements and adds new features
# to combat out-of-memory errors and prevent crash loops ("thrashing").
# VERSION 4.2: Fixes an UnboundLocalError by correctly handling global scope.

import os
import gc
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
MAX_FAILURES = 5
INACTIVITY_TIMEOUT_SECONDS = 3 * 60
MAIN_LOOP_POLLING_INTERVAL_SECONDS = 1.0

# --- LOGGING & VALIDATION ---
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

if not SHIP_INVITE_LINK:
    logging.critical("FATAL: SHIP_INVITE_LINK environment variable is not set!")
    exit(1)

# --- JAVASCRIPT PAYLOADS ---
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
CLIENT_SIDE_SCRIPT = """
(function() {
    'use strict';
    if (window.kingdomChatClientLoaded) { return; }
    window.kingdomChatClientLoaded = true;
    if (!window.py_bot_events) { window.py_bot_events = []; }
    console.log('[Kingdom Chat] Initializing client with enhanced monitoring...');
    const SERVER_URL = 'https://sortthechat.onrender.com/command';
    const MESSAGE_DELAY = 1200;
    const ZWSP = '\\u200B';
    let messageQueue = []; let isProcessingQueue = false; let chatObserver = null;
    function sendChat(mess) { const chatInp = document.getElementById("chat-input"); const chatBtn = document.getElementById("chat-send"); if (document.getElementById("chat")?.classList.contains('closed')) chatBtn?.click(); if (chatInp) chatInp.value = mess; chatBtn?.click(); }
    function queueReply(message) { const MAX_CONTENT_LENGTH=199; const splitLongMessage=(line)=>{const chunks=[];let t=String(line);if(t.length<=MAX_CONTENT_LENGTH)return chunks.push(t),chunks;for(;t.length>0;){if(t.length<=MAX_CONTENT_LENGTH){chunks.push(t);break}let n=t.lastIndexOf(" ",MAX_CONTENT_LENGTH);n<=0&&(n=MAX_CONTENT_LENGTH),chunks.push(t.substring(0,n).trim()),t=t.substring(n).trim()}return chunks}; (Array.isArray(message)?message:[message]).forEach(line=>{splitLongMessage(String(line)).forEach(chunk=>{chunk&&messageQueue.push(ZWSP+chunk)})}); !isProcessingQueue&&processQueue(); }
    function processQueue() { if (messageQueue.length === 0) { isProcessingQueue = false; return; } isProcessingQueue = true; const nextMessage = messageQueue.shift(); sendChat(nextMessage); setTimeout(processQueue, MESSAGE_DELAY); }
    function startChatMonitor() { if (chatObserver) return; console.log("[Kingdom Chat] Starting chat command monitor..."); const chatContent = document.getElementById("chat-content"); if (!chatContent) return; chatObserver = new MutationObserver(mutations => { mutations.forEach(mutation => { mutation.addedNodes.forEach(node => { if (node.nodeType !== 1 || node.tagName !== "P") return; const pTextContent = node.textContent || ""; if (pTextContent.startsWith(ZWSP)) return; if (pTextContent.includes("Joined ship '")) { const match = pTextContent.match(/{[A-Z\\d]+}/); if (match && match[0]) { window.py_bot_events.push({ type: 'ship_joined', id: match[0] }); } return; } const bdiMatch = node.innerHTML.match(/<bdi.*?>(.*?)<\\/bdi>/); if (!bdiMatch) return; const playerName = bdiMatch[1].trim(); const colonIdx = pTextContent.indexOf(':'); if (colonIdx === -1) return; const command = pTextContent.substring(colonIdx + 1).trim().split(' ')[0]; if (!command.startsWith('!')) return; window.py_bot_events.push({ type: 'command_processed' }); const args = pTextContent.substring(colonIdx + 1).trim().split(' ').slice(1); fetch(SERVER_URL, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ playerName, command, args }) }).then(r => r.json()).then(d => { if (d.replies && d.replies.length > 0) queueReply(d.replies); }).catch(e => console.error("KC Error:", e)); }); }); }); chatObserver.observe(chatContent, { childList: true }); }
    const waitForGame = setInterval(() => { if (document.getElementById("chat-content")) { clearInterval(waitForGame); console.log('[Kingdom Chat] Game detected!'); queueReply("👑 Kingdom Chat Client connected. Enhanced auto-rejoin is active."); startChatMonitor(); } }, 500);
})();
"""

# --- GLOBAL STATE ---
driver = None
inactivity_timer = None
BOT_STATE = {"status": "Initializing...", "start_time": datetime.now(), "current_ship_id": "N/A", "event_log": deque(maxlen=20)}

def log_event(message):
    timestamp = datetime.now().strftime('%H:%M:%S')
    full_message = f"[{timestamp}] {message}"
    BOT_STATE["event_log"].appendleft(full_message)
    logging.info(f"EVENT: {message}")

# --- BROWSER & FLASK SETUP ---
def setup_driver():
    logging.info("Launching headless browser with MEMORY-SAVING options...")
    chrome_options = Options()
    # chrome_options.binary_location = "/usr/bin/chromium"
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--mute-audio")
    chrome_options.add_argument("--blink-settings=imagesEnabled=false")
    chrome_options.add_argument("--single-process")
    chrome_options.add_argument("--disable-features=TranslateUI,BlinkGenPropertyTrees,ImprovedCookieControls,SameSiteByDefaultCookies,LazyFrameLoading")
    prefs = {"profile.managed_default_content_settings.images": 2, "profile.managed_default_content_settings.stylesheets": 2, "profile.managed_default_content_settings.fonts": 2}
    chrome_options.add_experimental_option("prefs", prefs)
    return webdriver.Chrome(options=chrome_options)

flask_app = Flask('')
@flask_app.route('/')
def health_check():
    uptime = str(datetime.now() - BOT_STATE['start_time']).split('.')[0]
    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="10"><title>Bot Status</title><style>body{{font-family:monospace;background-color:#1e1e1e;color:#d4d4d4;}}</style></head><body><h1>Selenium Bridge Bot Status</h1><p><b>Status:</b> {BOT_STATE['status']}</p><p><b>Ship ID:</b> {BOT_STATE['current_ship_id']}</p><p><b>Uptime:</b> {uptime}</p><h2>Event Log</h2><pre>{'<br>'.join(BOT_STATE['event_log'])}</pre></body></html>"""
    return Response(html, mimetype='text/html')

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    logging.info(f"Health check server listening on http://0.0.0.0:{port}")
    flask_app.run(host='0.0.0.0', port=port)

# --- CORE BOT FUNCTIONS ---
def reset_inactivity_timer():
    global inactivity_timer
    if inactivity_timer: inactivity_timer.cancel()
    inactivity_timer = threading.Timer(INACTIVITY_TIMEOUT_SECONDS, attempt_soft_rejoin)
    inactivity_timer.start()

def attempt_soft_rejoin():
    log_event("Game inactivity detected. Attempting proactive soft rejoin.")
    BOT_STATE["status"] = "Attempting Soft Rejoin..."
    global driver
    if not driver: return
    try:
        ship_id = BOT_STATE.get('current_ship_id')
        if not ship_id or ship_id == 'N/A': raise ValueError("Cannot rejoin, no known Ship ID.")
        try: driver.find_element(By.CSS_SELECTOR, "div#disconnect-popup button.btn-green").click()
        except: 
            try: driver.find_element(By.ID, "exit_button").click()
            except: pass
        wait = WebDriverWait(driver, 20)
        wait.until(EC.presence_of_element_located((By.ID, 'shipyard')))
        clicked = driver.execute_script("const sid=arguments[0];const s=Array.from(document.querySelectorAll('.sy-id')).find(e=>e.textContent===sid);if(s){s.click();return true}return false", ship_id)
        if not clicked: raise RuntimeError(f"Could not find ship {ship_id}")
        wait.until(EC.presence_of_element_located((By.ID, 'chat-input')))
        log_event("✅ Soft rejoin successful!"); BOT_STATE["status"] = "Running"; reset_inactivity_timer()
    except Exception as e:
        log_event(f"Soft rejoin FAILED: {e}. Triggering hard restart.")
        if driver: driver.quit()

def start_bot(use_key_login):
    global driver
    BOT_STATE["status"] = "Launching Browser..."
    log_event("Starting new Selenium session...")
    driver = setup_driver()
    driver.get("about:blank"); driver.execute_script(PERFORMANCE_BOOSTER_SCRIPT)
    driver.get(SHIP_INVITE_LINK)
    try:
        wait = WebDriverWait(driver, 20)
        btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".modal-container .btn-green"))); driver.execute_script("arguments[0].click();", btn)
        if ANONYMOUS_LOGIN_KEY and use_key_login:
            link = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(., 'Restore old anonymous key')]"))); driver.execute_script("arguments[0].click();", link)
            wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, 'div.modal-window input[maxlength="24"]'))).send_keys(ANONYMOUS_LOGIN_KEY)
            submit_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//div[.//h2[text()='Restore Account Key']]//button[contains(@class, 'btn-green')]"))); driver.execute_script("arguments[0].click();", submit_btn)
            wait.until(EC.invisibility_of_element_located((By.XPATH, "//div[.//h2[text()='Restore Account Key']]")))
        else:
            play_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Play Anonymously')]"))); driver.execute_script("arguments[0].click();", play_btn)
    except TimeoutException: log_event("Login form not found.")
    except Exception as e: log_event(f"Login error: {e}"); raise
    WebDriverWait(driver, 60).until(EC.presence_of_element_located((By.ID, "chat-input")))
    log_event("Game loaded.")
    driver.execute_script(CLIENT_SIDE_SCRIPT)
    PROACTIVE_SCAN_SCRIPT="const c=document.getElementById('chat-content');if(!c)return null;const p=c.querySelectorAll('p');for(let i=p.length-1;i>=0;i--){const t=p[i].textContent||'';if(t.includes(\"Joined ship '\")){const m=t.match(/{[A-Z\\d]+}/);if(m&&m[0])return m[0]}}return null";
    found_id=driver.execute_script(PROACTIVE_SCAN_SCRIPT);ship_id_found=False
    if found_id: BOT_STATE["current_ship_id"]=found_id;ship_id_found=True;log_event(f"✅ ID via scan: {found_id}")
    if not ship_id_found:
        start_time=time.time()
        while time.time()-start_time<15:
            try:
                new_events=driver.execute_script("return window.py_bot_events.splice(0,window.py_bot_events.length);")
                for event in new_events:
                    if event.get('type')=='ship_joined':BOT_STATE["current_ship_id"]=event['id'];ship_id_found=True;log_event(f"✅ ID via event: {event['id']}");break
                if ship_id_found:break
            except WebDriverException:break
            time.sleep(0.5)
    if not ship_id_found: raise RuntimeError("Failed to get Ship ID.")

# --- MAIN EXECUTION & LIFECYCLE MANAGEMENT ---
def main():
    # THIS IS THE FIX: Declare intent to modify the global `driver` variable.
    global driver 
    
    threading.Thread(target=run_flask, daemon=True).start()
    use_key_login = True
    failure_count = 0
    restart_timestamps = deque(maxlen=5)

    while failure_count < MAX_FAILURES:
        now = time.time()
        if len(restart_timestamps) == 5 and (now - restart_timestamps[0] < 600):
            log_event("CRITICAL: Bot is thrashing (restarting too frequently).")
            logging.critical("Pausing for 5 minutes to prevent crash loop...")
            BOT_STATE["status"] = "CRASH LOOP DETECTED - Paused for 5 minutes."
            time.sleep(300)
            restart_timestamps.clear()
        
        restart_timestamps.append(now)

        try:
            start_bot(use_key_login)
            log_event("Bot is running. Python is now monitoring game activity.")
            BOT_STATE["status"] = "Running (Monitoring JS client)"
            failure_count = 0 
            restart_timestamps.clear()
            reset_inactivity_timer()

            while True:
                time.sleep(MAIN_LOOP_POLLING_INTERVAL_SECONDS)
                new_events = driver.execute_script("return window.py_bot_events.splice(0, window.py_bot_events.length);")
                if new_events:
                    reset_inactivity_timer()
                    for event in new_events:
                        if event.get('type') == 'ship_joined' and event.get('id') != BOT_STATE["current_ship_id"]:
                            log_event(f"Detected switch to new ship: {event['id']}")
                            BOT_STATE["current_ship_id"] = event['id']
                _ = driver.window_handles 

        except WebDriverException as e:
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
            if inactivity_timer: inactivity_timer.cancel()
            if driver:
                try: driver.quit()
                except Exception: pass
                driver = None # This assignment is now safe because of `global driver`
            gc.collect()

            if failure_count < MAX_FAILURES:
                log_event(f"Waiting 10 seconds before restart...")
                time.sleep(10)
            else:
                log_event(f"FATAL: Reached {MAX_FAILURES} consecutive failures. Bot is stopping.")
                BOT_STATE["status"] = f"STOPPED after {MAX_FAILURES} failures."
                break

if __name__ == "__main__":
    main()
