# bot.py
# FINAL SMOOTH-REJOIN VERSION
# This version features a fully self-contained JavaScript client that handles
# in-game disconnections and rejoins automatically without requiring a full script restart.

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

# This is the new, self-sufficient client with built-in rejoin logic.
CLIENT_SIDE_SCRIPT = """
(function() {
    'use strict';

    if (window.kingdomChatClientLoaded) {
        console.log('[Kingdom Chat] Client already loaded. Skipping injection.');
        return;
    }
    window.kingdomChatClientLoaded = true;
    console.log('[Kingdom Chat] Initializing client with auto-rejoin logic...');

    // --- Configuration & Message Queue ---
    const SERVER_URL = 'https://sortthechat.onrender.com/command';
    const MESSAGE_DELAY = 1200;
    const ZWSP = '\\u200B';
    let messageQueue = [];
    let isProcessingQueue = false;
    let chatObserver = null;
    let disconnectMonitorInterval = null;

    function sendChat(mess) {
        const chatBox = document.getElementById("chat");
        const chatInp = document.getElementById("chat-input");
        const chatBtn = document.getElementById("chat-send");
        if (chatBox?.classList.contains('closed')) chatBtn?.click();
        if (chatInp) chatInp.value = mess;
        chatBtn?.click();
    }

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

    // --- Chat Command Monitor ---
    function startChatMonitor() {
        if (chatObserver) return;
        console.log("[Kingdom Chat] Starting chat command monitor...");
        const chatContent = document.getElementById("chat-content");
        if (!chatContent) return;

        chatObserver = new MutationObserver(mutations => {
            mutations.forEach(mutation => {
                mutation.addedNodes.forEach(node => {
                    if (node.nodeType !== 1 || node.tagName !== "P") return;
                    const pTextContent = node.textContent || "";
                    if (pTextContent.startsWith(ZWSP)) return;
                    const bdiMatch = node.innerHTML.match(/<bdi.*?>(.*?)<\\/bdi>/);
                    if (!bdiMatch) return;
                    const playerName = bdiMatch[1].trim();
                    const colonIdx = pTextContent.indexOf(':');
                    if (colonIdx === -1) return;
                    const commandText = pTextContent.substring(colonIdx + 1).trim();
                    const parts = commandText.split(' ');
                    const command = parts[0];
                    if (!command.startsWith('!')) return;

                    fetch(SERVER_URL, {
                        method: "POST", headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ playerName: playerName, command: command, args: parts.slice(1) })
                    }).then(response => response.json())
                    .then(data => { if (data.replies && data.replies.length > 0) { queueReply(data.replies); }})
                    .catch(error => console.error("[Kingdom Chat] Error sending command:", error));
                });
            });
        });
        chatObserver.observe(chatContent, { childList: true });
    }
    
    function stopAllMonitors() {
        if (chatObserver) {
            chatObserver.disconnect();
            chatObserver = null;
            console.log('[Kingdom Chat] Chat monitor stopped.');
        }
        if (disconnectMonitorInterval) {
            clearInterval(disconnectMonitorInterval);
            disconnectMonitorInterval = null;
            console.log('[Kingdom Chat] Disconnect monitor stopped.');
        }
    }

    // --- Automatic Rejoin Logic ---
    function handleRejoin() {
        console.log('[Kingdom Chat] Disconnect detected! Initiating automatic rejoin sequence.');
        stopAllMonitors();

        const disconnectPopup = document.querySelector('div#disconnect-popup');
        const returnButton = disconnectPopup?.querySelector('button.btn-green');

        if (returnButton) {
            returnButton.click();
            console.log('[Kingdom Chat] Clicked "Return to Menu". Waiting for menu screen...');
            const waitForMenu = setInterval(() => {
                const playButton = document.querySelector("button.btn-large.btn-green[style*='display: block']");
                if (playButton && playButton.textContent.includes('Play Anonymously')) {
                    clearInterval(waitForMenu);
                    console.log('[Kingdom Chat] Main menu detected. Reloading page to rejoin ship...');
                    location.reload();
                }
            }, 1000);
        } else {
            console.log('[Kingdom Chat] Could not find disconnect popup. Reloading page as a failsafe...');
            location.reload();
        }
    }

    function startDisconnectMonitor() {
        if (disconnectMonitorInterval) return;
        console.log('[Kingdom Chat] Starting disconnect monitor...');
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
                console.log('[Kingdom Chat] Game detected!');
                queueReply("👑 Kingdom Chat Client connected. Auto-rejoin logic is active.");
                startChatMonitor();
                startDisconnectMonitor();
            }
        }, 500);
    }

    initialize();
})();
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
    prefs = {"profile.managed_default_content_settings.images": 2, "profile.managed_default_content_settings.stylesheets": 2, "profile.managed_default_content_settings.fonts": 2}
    chrome_options.add_experimental_option("prefs", prefs)
    return webdriver.Chrome(options=chrome_options)

flask_app = Flask('')
@flask_app.route('/')
def health_check():
    uptime = str(datetime.now() - BOT_STATE['start_time']).split('.')[0]
    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="10"><title>Bot Status</title><style>body{{font-family:monospace;background-color:#1e1e1e;color:#d4d4d4;}}</style></head><body><h1>Selenium Bridge Bot Status</h1><p><b>Status:</b> {BOT_STATE['status']}</p><p><b>Uptime:</b> {uptime}</p><h2>Event Log</h2><pre>{'<br>'.join(BOT_STATE['event_log'])}</pre></body></html>"""
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
    
    log_event("Navigating to invite link...")
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

    log_event("Waiting for page to load before injecting client...")
    WebDriverWait(driver, 60).until(EC.presence_of_element_located((By.ID, "chat-input")))
    log_event("Game loaded.")

    log_event("Injecting full JavaScript client into the page...")
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
            log_event("Bot is running. Python is now monitoring browser responsiveness.")
            BOT_STATE["status"] = "Running (JS client is managing game state)"
            failure_count = 0

            # NEW, more lenient health check. Lets the JS handle in-game disconnects.
            # Only fails if the entire browser process dies.
            while True:
                time.sleep(60)
                _ = driver.title # A lightweight check to see if the browser is still alive.
                logging.info("Health Check: Browser process is responsive.")

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
