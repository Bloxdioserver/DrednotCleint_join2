# bot.py
# FINAL STABILIZED VERSION (with Pre-emptive Injection)
# This version loads a blank page first, injects performance scripts, and THEN
# navigates to the game. This is the most reliable method for resource-constrained environments.

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
MAX_FAILURES = 3

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
'use strict';
if (window.kingdomChatClientLoaded) {
    console.log('[Kingdom Chat] Client already loaded. Skipping injection.');
} else {
    window.kingdomChatClientLoaded = true;
    console.log('[Kingdom Chat] Initializing client...');
    const SERVER_URL = 'https://sortthechat.onrender.com/command';
    const MESSAGE_DELAY = 1200;
    const ZWSP = '\\u200B';
    const chatBox = document.getElementById("chat");
    const chatInp = document.getElementById("chat-input");
    const chatBtn = document.getElementById("chat-send");
    let messageQueue = [];
    let isProcessingQueue = false;
    function sendChat(mess) { if (chatBox?.classList.contains('closed')) chatBtn?.click(); if (chatInp) chatInp.value = mess; chatBtn?.click(); }
    function queueReply(message) {
        const MAX_CONTENT_LENGTH = 199;
        const splitLongMessage = (line) => {
            const chunks = []; let remainingText = String(line);
            if (remainingText.length <= MAX_CONTENT_LENGTH) { chunks.push(remainingText); return chunks; }
            while (remainingText.length > 0) {
                if (remainingText.length <= MAX_CONTENT_LENGTH) { chunks.push(remainingText); break; }
                let breakPoint = remainingText.lastIndexOf(' ', MAX_CONTENT_LENGTH);
                if (breakPoint <= 0) breakPoint = MAX_CONTENT_LENGTH;
                chunks.push(remainingText.substring(0, breakPoint).trim());
                remainingText = remainingText.substring(breakPoint).trim();
            } return chunks;
        };
        const linesToProcess = Array.isArray(message) ? message : [message];
        linesToProcess.forEach(line => { splitLongMessage(String(line)).forEach(chunk => { if (chunk) messageQueue.push(ZWSP + chunk); }); });
        if (!isProcessingQueue) processQueue();
    }
    function processQueue() {
        if (messageQueue.length === 0) { isProcessingQueue = false; return; }
        isProcessingQueue = true; const nextMessage = messageQueue.shift();
        sendChat(nextMessage); setTimeout(processQueue, MESSAGE_DELAY);
    }
    function monitorChat() {
        console.log("[Kingdom Chat] Monitoring for commands...");
        const observer = new MutationObserver(mutations => {
            mutations.forEach(mutation => {
                mutation.addedNodes.forEach(node => {
                    if (node.nodeType !== 1 || node.tagName !== "P") return;
                    const pTextContent = node.textContent || ""; if (pTextContent.startsWith(ZWSP)) return;
                    const bdiMatch = node.innerHTML.match(/<bdi.*?>(.*?)<\\/bdi>/); if (!bdiMatch) return;
                    const playerName = bdiMatch[1].trim(); const colonIdx = pTextContent.indexOf(':'); if (colonIdx === -1) return;
                    const commandText = pTextContent.substring(colonIdx + 1).trim(); const parts = commandText.split(' ');
                    const command = parts[0]; if (!command.startsWith('!')) return;
                    console.log(`[Kingdom Chat] Sending command '${command}' for player '${playerName}' to server.`);
                    fetch(SERVER_URL, {
                        method: "POST", headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ playerName: playerName, command: command, args: parts.slice(1) })
                    }).then(response => { if (!response.ok) { throw new Error(`HTTP error! status: ${response.status}`); } return response.json(); })
                    .then(data => { if (data.replies && Array.isArray(data.replies) && data.replies.length > 0) { queueReply(data.replies); }})
                    .catch(error => { console.error("[Kingdom Chat] Error sending command to server:", error); queueReply("Error: Could not connect to the game server."); });
                });
            });
        });
        observer.observe(document.getElementById("chat-content"), { childList: true });
    }
    function initialize() {
        const waitForChat = setInterval(() => {
            if (document.getElementById("chat-content") && document.getElementById("chat-input")) {
                clearInterval(waitForChat); monitorChat(); queueReply("👑 Kingdom Chat Client connected.");
            }
        }, 500);
    }
    initialize();
}
"""

# --- GLOBAL STATE ---
driver = None
BOT_STATE = {"status": "Initializing...", "start_time": datetime.now(), "event_log": deque(maxlen=20)}

def log_event(message):
    timestamp = datetime.now().strftime('%H:%M:%S')
    full_message = f"[{timestamp}] {message}"
    BOT_STATE["event_log"].appendleft(full_message)
    logging.info(f"EVENT: {message}")

# --- BROWSER & FLASK SETUP ---
def setup_driver():
    logging.info("Launching headless browser with STABILITY-focused performance options...")
    chrome_options = Options()
    chrome_options.binary_location = "/usr/bin/chromium"

    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--mute-audio")
    chrome_options.add_argument("--log-level=3")
    chrome_options.add_argument("--blink-settings=imagesEnabled=false")
    
    prefs = {
        "profile.managed_default_content_settings.images": 2,
        "profile.managed_default_content_settings.stylesheets": 2,
        "profile.managed_default_content_settings.fonts": 2
    }
    chrome_options.add_experimental_option("prefs", prefs)

    return webdriver.Chrome(options=chrome_options)

flask_app = Flask('')
@flask_app.route('/')
def health_check():
    uptime = str(datetime.now() - BOT_STATE['start_time']).split('.')[0]
    html = f"""
    <!DOCTYPE html><html lang="en">
    <head><meta charset="UTF-8"><meta http-equiv="refresh" content="10"><title>Bot Status</title>
    <style>body{{font-family:monospace;background-color:#1e1e1e;color:#d4d4d4;}}</style></head>
    <body><h1>Selenium Bridge Bot Status</h1>
    <p><b>Status:</b> {BOT_STATE['status']}</p>
    <p><b>Uptime:</b> {uptime}</p>
    <h2>Event Log</h2><pre>{'<br>'.join(BOT_STATE['event_log'])}</pre>
    </body></html>
    """
    return Response(html, mimetype='text/html')

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    logging.info(f"Health check server listening on http://0.0.0.0:{port}")
    flask_app.run(host='0.0.0.0', port=port)

# --- BOT STARTUP LOGIC ---
def start_bot(use_key_login):
    global driver
    BOT_STATE["status"] = "Launching Browser..."
    log_event("Starting new Selenium session...")
    driver = setup_driver()

    # --- PRE-EMPTIVE INJECTION TECHNIQUE ---
    # 1. Navigate to a harmless blank page first.
    log_event("Loading blank page for pre-emptive script injection...")
    driver.get("about:blank")

    # 2. Inject the performance-boosting script into the blank page.
    log_event("Injecting performance booster before navigating to game...")
    driver.execute_script(PERFORMANCE_BOOSTER_SCRIPT)
    log_event("Performance script is now active and waiting.")

    # 3. NOW, navigate to the actual game. The script is already active and will
    #    neuter the game's heavy components the moment they try to load.
    log_event(f"Navigating to invite link...")
    driver.get(SHIP_INVITE_LINK)

    try:
        wait = WebDriverWait(driver, 20)
        btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".modal-container .btn-green")))
        driver.execute_script("arguments[0].click();", btn)
        logging.info("Clicked 'Accept' on notice.")

        if ANONYMOUS_LOGIN_KEY and use_key_login:
            log_event("Attempting login with saved key.")
            link = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(., 'Restore old anonymous key')]")))
            driver.execute_script("arguments[0].click();", link)
            wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, 'div.modal-window input[maxlength="24"]'))).send_keys(ANONYMOUS_LOGIN_KEY)
            submit_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//div[.//h2[text()='Restore Account Key']]//button[contains(@class, 'btn-green')]")))
            driver.execute_script("arguments[0].click();", submit_btn)
            wait.until(EC.invisibility_of_element_located((By.XPATH, "//div[.//h2[text()='Restore Account Key']]")))
            logging.info("Login key submitted.")
        else:
            log_event("Playing as new guest.")
            play_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Play Anonymously')]")))
            driver.execute_script("arguments[0].click();", play_btn)

    except TimeoutException:
        log_event("Login form not found, assuming already in-game.")
    except Exception as e:
        log_event(f"Critical error during login: {e}")
        raise

    log_event("Waiting for chat to become available...")
    WebDriverWait(driver, 60).until(EC.presence_of_element_located((By.ID, "chat-input")))
    log_event("Chat is available.")

    log_event("Injecting main JavaScript client into the page...")
    driver.execute_script(CLIENT_SIDE_SCRIPT)
    log_event("JavaScript client injected successfully. Bot setup complete.")

# --- MAIN EXECUTION & LIFECYCLE MANAGEMENT ---
def main():
    threading.Thread(target=run_flask, daemon=True).start()
    use_key_login = True
    failure_count = 0

    while failure_count < MAX_FAILURES:
        try:
            start_bot(use_key_login)
            log_event("Bot is running. Monitoring game state.")
            BOT_STATE["status"] = "Running (Client active)"
            failure_count = 0

            while True:
                time.sleep(90)
                driver.find_element(By.ID, "chat-input")

        except Exception as e:
            failure_count += 1
            BOT_STATE["status"] = f"Crashed! Restarting... (Failure {failure_count}/{MAX_FAILURES})"
            log_event(f"CRITICAL ERROR (Failure #{failure_count}): {e}")
            traceback.print_exc()

            if "invalid" in str(e).lower():
                log_event("Login key may be invalid. Will try as Guest on next restart.")
                use_key_login = False
        finally:
            if driver:
                try: driver.quit()
                except Exception: pass

            if failure_count < MAX_FAILURES:
                time.sleep(10)
            else:
                log_event(f"FATAL: Reached {MAX_FAILURES} consecutive failures. Bot is stopping.")
                BOT_STATE["status"] = f"STOPPED after {MAX_FAILURES} failures."
                logging.critical("Bot has been shut down permanently due to repeated errors.")

if __name__ == "__main__":
    main()
