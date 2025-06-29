# joiner_bot.py (Version 2.0 - Multi-Bot Pool)
# A standalone bot that manages a pool of instances and dispatches them on request.

import os
import time
import shutil
import threading
import traceback
from threading import Lock

from flask import Flask, Response, request
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import WebDriverException, TimeoutException, NoSuchElementException

# --- CONFIGURATION ---
# The number of bot instances to run. Can be set as an environment variable.
NUM_BOTS = int(os.environ.get("NUM_BOTS", 3))
API_KEY = 'drednot123'
ANONYMOUS_LOGIN_KEY = '_M85tFxFxIRDax_nh-HYm1gT'

# --- GLOBAL STATE & LOCKS ---

# A class to hold the state and driver for each bot instance
class BotInstance:
    def __init__(self, bot_id):
        self.id = bot_id
        self.driver = None
        self.status = "Initializing"
        self.current_ship_id = "N/A"
        self.last_action_timestamp = time.time()

# The pool of bot instances and a lock to ensure thread-safe access
bot_pool = []
bot_pool_lock = Lock()

# --- BROWSER (SELENIUM) SETUP ---

def find_chromium_executable():
    path = shutil.which('chromium') or shutil.which('chromium-browser')
    if path: return path
    raise FileNotFoundError("Could not find 'chromium' or 'chromium-browser' executable. Please install it.")

def setup_driver():
    """Configures and launches a single headless Chrome browser."""
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--mute-audio")
    chrome_options.add_argument("--disable-images")
    chrome_options.add_argument("--blink-settings=imagesEnabled=false")
    try:
        chrome_options.binary_location = find_chromium_executable()
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
        exit(1)
    return webdriver.Chrome(options=chrome_options)

def start_single_bot(bot: BotInstance):
    """Initializes one bot instance, logs it in, and leaves it at the main menu."""
    print(f"[BOT-{bot.id}] Starting instance...")
    try:
        bot.driver = setup_driver()
        bot.status = "Navigating"
        bot.driver.get("https://drednot.io/")
        wait = WebDriverWait(bot.driver, 20)
        
        btn_accept = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".modal-container .btn-green")))
        bot.driver.execute_script("arguments[0].click();", btn_accept)
        
        if ANONYMOUS_LOGIN_KEY:
            link = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(., 'Restore old anonymous key')]")))
            bot.driver.execute_script("arguments[0].click();", link)
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'div.modal-window input[maxlength="24"]'))).send_keys(ANONYMOUS_LOGIN_KEY)
            submit_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//div[.//h2[text()='Restore Account Key']]//button[contains(@class, 'btn-green')]")))
            bot.driver.execute_script("arguments[0].click();", submit_btn)
        else:
            play_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Play Anonymously')]")))
            bot.driver.execute_script("arguments[0].click();", play_btn)

        wait.until(EC.presence_of_element_located((By.ID, 'shipyard')))
        bot.status = "Idle - Awaiting Join Command"
        bot.last_action_timestamp = time.time()
        print(f"[BOT-{bot.id}] Instance is ready and waiting at the main menu.")
    except Exception as e:
        print(f"[BOT-{bot.id}] [ERROR] Failed to initialize: {e}")
        bot.status = "Error - Initialization Failed"
        if bot.driver:
            bot.driver.quit()

def initialize_bot_pool():
    """Creates and starts all bot instances defined by NUM_BOTS."""
    print(f"[SYSTEM] Initializing a pool of {NUM_BOTS} bot(s)...")
    for i in range(NUM_BOTS):
        bot = BotInstance(bot_id=i)
        bot_pool.append(bot)
        # We start them sequentially to avoid overwhelming the system on startup
        start_single_bot(bot)
    print("[SYSTEM] All bot instances initialized.")

# --- CORE JOIN LOGIC ---

def send_chat(bot: BotInstance, message: str):
    if not bot.driver: return
    try:
        bot.driver.execute_script("""
            const msg = arguments[0]; const chatBox = document.getElementById('chat');
            const chatInp = document.getElementById('chat-input'); const chatBtn = document.getElementById('chat-send');
            if (chatBox && chatBox.classList.contains('closed')) { chatBtn.click(); }
            if (chatInp) { chatInp.value = msg; }
            chatBtn.click();
        """, message)
    except WebDriverException:
        print(f"[BOT-{bot.id}] [WARN] Could not send chat message. Browser might have closed.")

def perform_join_ship(bot: BotInstance, new_ship_id: str):
    """The main function to make a specific bot instance join a ship."""
    if not bot.driver:
        print(f"[BOT-{bot.id}] [ERROR] Join command received, but browser is not running.")
        bot.status = "Error - No Driver"
        return

    with bot_pool_lock:
        bot.status = f"Joining ship {new_ship_id}..."
        bot.last_action_timestamp = time.time()
    
    print(f"[BOT-{bot.id}] [JOIN] Attempting to join new ship: {new_ship_id}")

    try:
        # Step 1: Intelligently return to the main menu
        try:
            exit_button = WebDriverWait(bot.driver, 3).until(EC.element_to_be_clickable((By.ID, "exit_button")))
            bot.driver.execute_script("arguments[0].click();", exit_button)
            WebDriverWait(bot.driver, 15).until(EC.presence_of_element_located((By.ID, 'shipyard')))
        except TimeoutException:
            pass # Already at the main menu

        # Step 2: Find the ship and click it
        wait = WebDriverWait(bot.driver, 15)
        wait.until(EC.presence_of_element_located((By.ID, 'shipyard')))
        
        js_find_and_click = """
            const sid = arguments[0]; const elems = Array.from(document.querySelectorAll('.sy-id'));
            const target = elems.find(e => e.textContent === sid);
            if (target) { target.click(); return true; }
            document.querySelector('#shipyard section:nth-of-type(3) .btn-small')?.click(); return false;
        """
        clicked = bot.driver.execute_script(js_find_and_click, new_ship_id)
        if not clicked:
            time.sleep(1.5)
            clicked = bot.driver.execute_script(js_find_and_click, new_ship_id)
        if not clicked:
            raise RuntimeError(f"Could not find ship {new_ship_id} in list.")

        # Step 3: Confirm join and update state
        wait.until(EC.presence_of_element_located((By.ID, 'chat-input')))
        
        print(f"[BOT-{bot.id}] [SUCCESS] Joined ship {new_ship_id}!")
        time.sleep(1)
        send_chat(bot, "Joiner bot has arrived.")

        with bot_pool_lock:
            bot.status = f"In Ship: {new_ship_id}"
            bot.current_ship_id = new_ship_id
            bot.last_action_timestamp = time.time()

    except Exception as e:
        print(f"[BOT-{bot.id}] [ERROR] A critical error occurred while trying to join ship: {e}")
        traceback.print_exc()
        with bot_pool_lock:
            bot.status = "Error - Join Failed"

# --- WEB SERVER (FLASK) ---

flask_app = Flask('')

@flask_app.route('/')
def health_check():
    """Provides a detailed status page for the entire bot pool."""
    html = """
    <html><head><title>Bot Pool Status</title><meta http-equiv="refresh" content="5"></head>
    <body style="font-family: sans-serif; background-color: #1e1e1e; color: #d4d4d4;">
        <h1>Drednot.io Joiner Bot Pool</h1>
        <table border="1" style="border-collapse: collapse; width: 100%;">
            <thead style="background-color: #3c3c3c;">
                <tr><th>Bot ID</th><th>Status</th><th>Current Ship</th><th>Last Action</th></tr>
            </thead>
            <tbody>
    """
    with bot_pool_lock:
        for bot in bot_pool:
            status_color = "#f44747" if "Error" in bot.status else ("#dccd85" if "Joining" in bot.status else "#73c991")
            html += f"""
                <tr style="background-color: #252526;">
                    <td style="padding: 8px; text-align: center;">{bot.id}</td>
                    <td style="padding: 8px; color: {status_color};">{bot.status}</td>
                    <td style="padding: 8px;">{bot.current_ship_id}</td>
                    <td style="padding: 8px;">{time.ctime(bot.last_action_timestamp)}</td>
                </tr>
            """
    html += "</tbody></table></body></html>"
    return Response(html, mimetype='text/html')

@flask_app.route('/join-request', methods=['POST'])
def handle_join_request():
    """Finds an available bot from the pool and dispatches it."""
    if request.headers.get('x-api-key') != API_KEY:
        return Response('{"error": "Invalid API key"}', status=401, mimetype='application/json')
    data = request.get_json()
    if not data or 'shipId' not in data:
        return Response('{"error": "Missing shipId"}', status=400, mimetype='application/json')
    
    new_ship_id = data['shipId']
    print(f"[SYSTEM] Received valid join request for ship: {new_ship_id}")
    
    chosen_bot = None
    with bot_pool_lock:
        # First, try to find a completely idle bot
        for bot in bot_pool:
            if bot.status == "Idle - Awaiting Join Command":
                chosen_bot = bot
                break
        
        # If no idle bots, grab one that's already in another ship (but not errored or busy)
        if not chosen_bot:
            for bot in bot_pool:
                if "In Ship" in bot.status:
                    chosen_bot = bot
                    break
    
    if chosen_bot:
        print(f"[SYSTEM] Dispatching Bot-{chosen_bot.id} to ship {new_ship_id}.")
        threading.Thread(target=perform_join_ship, args=(chosen_bot, new_ship_id)).start()
        return Response('{"status": "Bot dispatched"}', status=200, mimetype='application/json')
    else:
        print("[SYSTEM] [WARN] No available bots to handle join request.")
        return Response('{"error": "All bots are currently busy or in an error state"}', status=503, mimetype='application/json')

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    print(f"[SYSTEM] Web server listening on port {port}")
    flask_app.run(host='0.0.0.0', port=port)

# --- MAIN EXECUTION ---
if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    try:
        initialize_bot_pool()
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\n[SYSTEM] Shutdown signal received...")
    finally:
        print("[SYSTEM] Closing all browser instances...")
        for bot in bot_pool:
            if bot.driver:
                try:
                    bot.driver.quit()
                    print(f"[BOT-{bot.id}] Instance closed.")
                except Exception as e:
                    print(f"[BOT-{bot.id}] Error on quit: {e}")
        print("[SYSTEM] Shutdown complete.")
