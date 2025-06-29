# drednot_bot.py (Version 7.0 - Command Architecture)
# Implements a command queue for serialized, stable actions, centralized
# state management for thread safety, and Selenium best practices.

import os
import time
import shutil
import queue
import threading
import traceback
from datetime import datetime
from collections import deque
from threading import Lock, Event

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

MESSAGE_DELAY_SECONDS = 1.1
ZWSP = '\u200B'
PROACTIVE_REJOIN_TIMEOUT_SECONDS = 2 * 60 # 2 minutes

# --- JAVASCRIPT SNIPPETS ---
JS_CLICK_SCRIPT = "arguments[0].click();"

JS_ATOMIC_FIND_AND_JOIN = """
    const targetId = arguments[0];
    const maxAttempts = 3;
    const delayBetweenAttempts = 750; // ms

    // Helper function to find and click the ship by its ID
    const findAndClick = () => {
        const idSpans = Array.from(document.querySelectorAll('.sy-id'));
        const targetSpan = idSpans.find(span => span.textContent === targetId);
        if (targetSpan) {
            const clickableDiv = targetSpan.parentElement;
            clickableDiv.click();
            return true; // Indicate success
        }
        return false; // Indicate failure
    };

    // Main async logic to handle retries and refreshes
    return (async () => {
        for (let i = 0; i < maxAttempts; i++) {
            console.log(`[Bot-JS] Join attempt ${i + 1} for ${targetId}`);
            if (findAndClick()) {
                console.log(`[Bot-JS] Found and clicked ${targetId} on attempt ${i + 1}.`);
                return { success: true, method: i === 0 ? 'optimistic' : 'refresh' };
            }

            if (i < maxAttempts - 1) {
                const refreshButton = Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('Refresh'));
                if (refreshButton) {
                    refreshButton.click();
                    console.log('[Bot-JS] Refreshing list...');
                    await new Promise(resolve => setTimeout(resolve, delayBetweenAttempts));
                } else {
                    return { success: false, error: 'Refresh button not found' };
                }
            }
        }
        console.error(`[Bot-JS] Failed to find ${targetId} after ${maxAttempts} attempts.`);
        return { success: false, error: 'Ship not found after all retries' };
    })();
"""

JS_SEND_CHAT = """
    const msg = arguments[0];
    const chatInp = document.getElementById('chat-input');
    const chatBtn = document.getElementById('chat-send');
    if (chatInp && chatBtn) {
        chatInp.value = msg;
        // Dispatch an 'input' event to ensure the game's framework recognizes the change.
        chatInp.dispatchEvent(new Event('input', { bubbles: true, cancelable: true }));
        chatBtn.click();
        return true;
    }
    return false;
"""

JS_PULL_JOIN_EVENT = """
    // Atomically retrieve and clear the first 'ship_joined' event
    const events = window.py_bot_events || [];
    const joinEventIndex = events.findIndex(e => e.type === 'ship_joined');
    if (joinEventIndex > -1) {
        // Splice returns an array of removed items, we want the first one
        const event = events.splice(joinEventIndex, 1)[0];
        return event.id;
    }
    return null; // No event found
"""

MUTATION_OBSERVER_SCRIPT = """
    console.log('[Bot-JS] Initializing join event observer...');
    window.py_bot_events = [];
    const targetNode = document.getElementById('chat-content');
    if (!targetNode) return;
    const callback = (mutations) => {
        for (const mutation of mutations) {
            if (mutation.type !== 'childList') continue;
            for (const node of mutation.addedNodes) {
                if (node.nodeType !== 1 || !node.textContent) continue;
                if (node.textContent.includes("Joined ship '")) {
                    const match = node.textContent.match(/{[A-Z\\d]+}/);
                    if (match) window.py_bot_events.push({ type: 'ship_joined', id: match[0] });
                }
            }
        }
    };
    new MutationObserver(callback).observe(targetNode, { childList: true });
"""

# --- ARCHITECTURE: STATE & COMMANDS ---
class BotState:
    def __init__(self):
        self._lock = Lock()
        self.status = "Initializing..."
        self.current_ship_id = "N/A"
        self.last_command_info = "None yet."
        self.event_log = deque(maxlen=20)

    def update(self, status=None, ship_id=None, last_cmd=None):
        with self._lock:
            if status is not None: self.status = status
            if ship_id is not None: self.current_ship_id = ship_id
            if last_cmd is not None: self.last_command_info = last_cmd

    def log_event(self, message):
        with self._lock:
            timestamp = datetime.now().strftime('%H:%M:%S')
            self.event_log.appendleft(f"[{timestamp}] {message}")

    def get_snapshot(self):
        with self._lock:
            return {
                "status": self.status,
                "current_ship_id": self.current_ship_id,
                "last_command_info": self.last_command_info,
                "event_log": list(self.event_log)
            }

class InvalidKeyError(Exception): pass

# --- GLOBAL STATE (MANAGED) ---
bot_state = BotState()
command_queue = queue.Queue(maxsize=50)
message_output_queue = queue.Queue(maxsize=20)
driver_lock = Lock()
rejoin_timer = None
driver = None

# --- BROWSER & FLASK SETUP ---
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
    chrome_options.add_argument("--blink-settings=imagesEnabled=false")
    chrome_options.add_argument("--mute-audio")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36")
    try:
        chrome_options.binary_location = find_chromium_executable()
    except FileNotFoundError as e:
        print(f"FATAL: {e}"); exit(1)
    return webdriver.Chrome(options=chrome_options)

flask_app = Flask('')
@flask_app.route('/')
def health_check():
    state = bot_state.get_snapshot()
    html = f"""
    <!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="10">
    <title>Bot Status v7.0</title><style>body{{font-family:'Courier New',monospace;background-color:#1e1e1e;color:#d4d4d4;padding:20px;}}.container{{max-width:800px;margin:auto;background-color:#252526;border:1px solid #373737;padding:20px;border-radius:8px;}}h1{{color:#4ec9b0;}}p{{line-height:1.6;}}.status-ok{{color:#73c991;}}.status-warn{{color:#dccd85;}}.status-err{{color:#f44747;}}.label{{color:#9cdcfe;font-weight:bold;}}ul{{list-style-type:none;padding-left:0;}}li{{background-color:#2d2d2d;margin-bottom:8px;padding:10px;border-radius:4px;}}</style></head>
    <body><div class="container"><h1>Bot Status v7.0</h1>
    <p><span class="label">Status:</span> <span class="status-ok">{state['status']}</span></p>
    <p><span class="label">Current Ship ID:</span> {state['current_ship_id']}</p>
    <p><span class="label">Last Command:</span> {state['last_command_info']}</p>
    <h2>Recent Events</h2><ul>{''.join(f'<li>{event}</li>' for event in state['event_log'])}</ul></div></body></html>
    """
    return Response(html, mimetype='text/html')

@flask_app.route('/command', methods=['POST'])
def handle_command():
    reset_proactive_rejoin_timer()
    if request.headers.get('x-api-key') != API_KEY:
        return Response('{"error": "Invalid API key"}', status=401)

    data = request.get_json()
    if not data or 'type' not in data:
        return Response('{"error": "Missing command type"}', status=400)

    cmd_type = data['type'].upper()
    cmd_payload = data.get('payload')

    try:
        command_queue.put({'type': cmd_type, 'payload': cmd_payload}, timeout=2)
        bot_state.log_event(f"CMD QUEUED: {cmd_type} ({cmd_payload or ''})")
        return Response(f'{{"status": "Command {cmd_type} queued."}}', status=202)
    except queue.Full:
        return Response('{"error": "Command queue is full, try again later."}', status=503)

def run_flask():
    port = int(os.environ.get("PORT", 8000))
    print(f"Bot API v7.0 listening on port {port}")
    flask_app.run(host='0.0.0.0', port=port)

# --- COMMAND AND MESSAGE PROCESSORS ---
def command_processor_thread(stop_event):
    """Processes commands from the command_queue one by one."""
    while not stop_event.is_set():
        try:
            command = command_queue.get(timeout=1)
            cmd_type = command['type']
            payload = command['payload']
            bot_state.update(last_cmd=f"{cmd_type} {str(payload or '')[:50]}")

            with driver_lock:
                if not driver:
                    bot_state.log_event(f"WARN: Dropped command {cmd_type} (browser offline).")
                    continue

                if cmd_type == 'JOIN':
                    perform_in_session_join(payload)
                elif cmd_type == 'LEAVE':
                    perform_leave_ship()
                elif cmd_type == 'SAY':
                    queue_reply(payload)
                elif cmd_type == 'PROACTIVE_REJOIN':
                    perform_proactive_rejoin()
                else:
                    bot_state.log_event(f"ERROR: Unknown command type '{cmd_type}'")
            command_queue.task_done()
        except queue.Empty:
            continue
        except Exception as e:
            handle_critical_error(f"in command_processor for {command.get('type', 'N/A')}", e)

def message_processor_thread(stop_event):
    """Sends queued chat messages to the game."""
    while not stop_event.is_set():
        try:
            message = message_output_queue.get(timeout=1)
            with driver_lock:
                if driver:
                    driver.execute_script(JS_SEND_CHAT, message)
            time.sleep(MESSAGE_DELAY_SECONDS) # Respect rate limit
        except queue.Empty:
            continue
        except WebDriverException:
            pass # Driver closed, loop will exit on next check.

# --- CORE LOGIC (ACTIONS) ---
def handle_critical_error(err_message, exception):
    bot_state.update(status="Error! Restarting...")
    bot_state.log_event(f"CRITICAL: {err_message} - {exception}")
    print(f"❌ [CRITICAL] {err_message}: {exception}")
    traceback.print_exc()

def reset_proactive_rejoin_timer():
    global rejoin_timer
    if rejoin_timer: rejoin_timer.cancel()
    # When the timer fires, it adds a command to the queue, ensuring serialized execution
    rejoin_timer = threading.Timer(PROACTIVE_REJOIN_TIMEOUT_SECONDS, lambda: command_queue.put({'type': 'PROACTIVE_REJOIN', 'payload': None}))
    rejoin_timer.start()

def queue_reply(message):
    try:
        message_output_queue.put(ZWSP + message, timeout=2)
    except queue.Full:
        bot_state.log_event("[WARN] Message output queue is full.")

# Note: The following action functions assume the driver_lock is already held.
def perform_in_session_join(target_ship_id):
    bot_state.log_event(f"JOIN: Starting for {target_ship_id}.")
    print(f"[JOIN] Starting atomic sequence for {target_ship_id}.")
    try:
        wait = WebDriverWait(driver, 10)
        bot_state.update(status="Exiting current ship...")
        try:
            exit_button = WebDriverWait(driver, 3).until(EC.element_to_be_clickable((By.ID, "exit_button")))
            driver.execute_script(JS_CLICK_SCRIPT, exit_button)
        except TimeoutException:
            pass # Already at main menu
        wait.until(EC.presence_of_element_located((By.ID, 'shipyard')))

        bot_state.update(status=f"Searching for {target_ship_id}...")
        join_result = driver.execute_script(JS_ATOMIC_FIND_AND_JOIN, target_ship_id)
        if not join_result or not join_result.get('success'):
            raise RuntimeError(f"Could not find ship {target_ship_id}. Reason: {join_result.get('error', 'Unknown')}")

        print(f"[JOIN] Click successful via {join_result['method']} method. Waiting for confirmation...")

        new_ship_id = WebDriverWait(driver, 15, poll_frequency=0.2).until(
            lambda d: d.execute_script(JS_PULL_JOIN_EVENT),
            "Timed out waiting for 'ship_joined' event from game."
        )

        bot_state.update(status=f"In Ship: {new_ship_id}", ship_id=new_ship_id)
        bot_state.log_event(f"SUCCESS: Joined {new_ship_id}.")
        print(f"✅ [JOIN] Successfully joined {new_ship_id}!")
        queue_reply("Bot has arrived.")
    except Exception as e:
        handle_critical_error(f"Join sequence failed for {target_ship_id}", e)

def perform_leave_ship():
    bot_state.log_event("LEAVE: Starting leave sequence.")
    print("[LEAVE] Starting leave sequence.")
    try:
        bot_state.update(status="Leaving ship...")
        exit_button = WebDriverWait(driver, 3).until(EC.element_to_be_clickable((By.ID, "exit_button")))
        driver.execute_script(JS_CLICK_SCRIPT, exit_button)
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, 'shipyard')))
        bot_state.update(status="At Main Menu", ship_id="N/A")
        bot_state.log_event("SUCCESS: Left ship."); print("✅ [LEAVE] Successfully left ship.")
    except TimeoutException:
        bot_state.update(status="At Main Menu", ship_id="N/A")
        bot_state.log_event("INFO: Leave ignored, already at main menu.")
    except Exception as e:
        handle_critical_error("Leave sequence failed", e)

def perform_proactive_rejoin():
    ship_id_to_rejoin = bot_state.get_snapshot()['current_ship_id']
    if not ship_id_to_rejoin or ship_id_to_rejoin == "N/A":
        bot_state.log_event("REJOIN: Inactivity detected, but not in a ship. Skipping.")
        reset_proactive_rejoin_timer()
        return

    bot_state.log_event(f"REJOIN: Inactivity detected. Attempting to rejoin {ship_id_to_rejoin}.")
    print(f"[REJOIN] No activity for {PROACTIVE_REJOIN_TIMEOUT_SECONDS}s. Attempting to rejoin {ship_id_to_rejoin}.")
    bot_state.update(status="Proactive Rejoin...")
    try:
        try:
            # First, check for the disconnect pop-up which takes priority
            disconnect_button = WebDriverWait(driver, 2).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "#disconnect-popup button")))
            driver.execute_script(JS_CLICK_SCRIPT, disconnect_button); print("[REJOIN] Clicked disconnect pop-up button.")
        except TimeoutException:
            # If no pop-up, try the normal exit button
            exit_button = WebDriverWait(driver, 2).until(EC.element_to_be_clickable((By.ID, "exit_button")))
            driver.execute_script(JS_CLICK_SCRIPT, exit_button); print("[REJOIN] Clicked exit button.")

        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, 'shipyard')))
        print(f"[REJOIN] At main menu. Searching for {ship_id_to_rejoin}...")

        # Use the atomic join function for a fast and reliable rejoin
        join_result = driver.execute_script(JS_ATOMIC_FIND_AND_JOIN, ship_id_to_rejoin)
        if not join_result or not join_result.get('success'):
             raise RuntimeError(f"Could not find ship {ship_id_to_rejoin} to rejoin.")

        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.ID, 'chat-input')))
        bot_state.update(status=f"In Ship: {ship_id_to_rejoin}")
        bot_state.log_event(f"SUCCESS: Proactive rejoin to {ship_id_to_rejoin} successful.")
        print(f"✅ [REJOIN] Successfully rejoined {ship_id_to_rejoin}!")
        reset_proactive_rejoin_timer()
    except Exception as e:
        handle_critical_error(f"Proactive rejoin failed for ship {ship_id_to_rejoin}", e)

# --- BOT LIFECYCLE ---
def start_bot_session():
    """Initializes a new browser session and logs into the game."""
    global driver
    bot_state.update(status="Launching Browser...")
    bot_state.log_event(f"Starting into waiting room: {DEFAULT_SHIP_INVITE_LINK}")
    driver = setup_driver()
    with driver_lock:
        driver.get(DEFAULT_SHIP_INVITE_LINK); print(f"Navigating to: {DEFAULT_SHIP_INVITE_LINK}")
        wait = WebDriverWait(driver, 20)
        try:
            accept_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//div[contains(@class, 'modal-container')]//button[contains(., 'Accept')]")))
            driver.execute_script(JS_CLICK_SCRIPT, accept_button); print("[SETUP] Clicked 'Accept' on notice.")
            if ANONYMOUS_LOGIN_KEY:
                log_event("Attempting login with key."); print("[SETUP] Attempting to log in with anonymous key.")
                link = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(., 'Restore old anonymous key')]")))
                driver.execute_script(JS_CLICK_SCRIPT, link); print("[SETUP] Clicked 'Restore old anonymous key'.")
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'div.modal-window input[maxlength="24"]'))).send_keys(ANONYMOUS_LOGIN_KEY)
                submit_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//div[.//h2[text()='Restore Account Key']]//button[contains(@class, 'btn-green')]")))
                driver.execute_script(JS_CLICK_SCRIPT, submit_btn); print("[SETUP] Submitted key.")
                wait.until(EC.any_of(EC.presence_of_element_located((By.ID, "chat-input")),EC.presence_of_element_located((By.XPATH, "//h2[text()='Login Failed']"))))
                if driver.find_elements(By.XPATH, "//h2[text()='Login Failed']"): raise InvalidKeyError("Login Failed! Key may be invalid.")
                print("✅ [SETUP] Successfully logged in with key."); bot_state.log_event("Login with key successful.")
            else:
                bot_state.log_event("Playing as new guest (no key provided).")
                play_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Play Anonymously')]")));
                driver.execute_script(JS_CLICK_SCRIPT, play_button)
                print("[SETUP] Clicked 'Play Anonymously'.")

            WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.ID, "chat-input")))
            driver.execute_script(MUTATION_OBSERVER_SCRIPT); bot_state.log_event("In-game, observer active.")

            print("[SETUP] Waiting for Ship ID from join event...")
            found_id = WebDriverWait(driver, 15, poll_frequency=0.2).until(
                lambda d: d.execute_script(JS_PULL_JOIN_EVENT),
                "Timed out waiting for initial 'ship_joined' event."
            )

            bot_state.update(status="Waiting for command...", ship_id=found_id)
            bot_state.log_event(f"Confirmed in waiting room: {found_id}")
            print(f"✅ Successfully joined waiting room: {found_id}")

        except Exception as e:
            bot_state.log_event(f"Login failed critically: {e}"); raise

    queue_reply("Bot is online and waiting for commands.")
    reset_proactive_rejoin_timer()

def run_bot_lifecycle():
    print("[SYSTEM] Initializing bot lifecycle v7.0...")

    stop_event = Event()
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=command_processor_thread, args=(stop_event,), daemon=True).start()
    threading.Thread(target=message_processor_thread, args=(stop_event,), daemon=True).start()

    restart_count = 0; last_restart_time = time.time()
    while True:
        try:
            start_bot_session()
            # If start_bot_session returns successfully, the bot is running.
            # We wait here. The loop will only continue if start_bot_session throws an exception.
            # A graceful shutdown mechanism could signal this event.
            stop_event.wait()
        except InvalidKeyError as e:
            handle_critical_error("Invalid Anonymous Key", e)
            print("FATAL: The provided Anonymous Key is invalid. The bot will not restart. Please fix the key and restart the script manually.")
            stop_event.set() # Stop all threads
            break # Exit the lifecycle loop
        except Exception as e:
            handle_critical_error("in main bot session", e)
        finally:
            if stop_event.is_set():
                break # Exit if a fatal, non-recoverable error occurred

            global driver
            if rejoin_timer: rejoin_timer.cancel()
            if driver:
                try: driver.quit()
                except: pass
            driver = None

            # Thrashing detection
            current_time = time.time()
            if current_time - last_restart_time < 3600: restart_count += 1
            else: restart_count = 1
            last_restart_time = current_time

            if restart_count > 15:
                print("CRITICAL: Bot is thrashing. Pausing for 5 minutes.")
                bot_state.log_event("CRITICAL: Thrashing detected. Pausing.")
                time.sleep(300)

            time.sleep(5) # Cooldown before restarting the session.

if __name__ == "__main__":
    run_bot_lifecycle()
