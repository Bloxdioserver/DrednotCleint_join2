# joiner_bot.py
# A standalone, minimal bot that listens for an HTTP request and joins a specific Drednot.io ship.

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
# This key MUST match the API_KEY in your Tampermonkey script for security.
API_KEY = 'drednot123'
# Optional: Use a restore key to have a consistent name for your bot.
# Leave as None or '' to join as a new guest every time.
ANONYMOUS_LOGIN_KEY = '_M85tFxFxIRDax_nh-HYm1gT' # Replace with your bot's key if you have one.

# --- GLOBAL STATE & LOCKS ---
driver = None
driver_lock = Lock()
BOT_STATE = {
    "status": "Initializing...",
    "current_ship_id": "N/A",
    "last_action_timestamp": time.time()
}

# --- BROWSER (SELENIUM) SETUP ---

def find_chromium_executable():
    """Finds the path to the chromium executable."""
    path = shutil.which('chromium') or shutil.which('chromium-browser')
    if path:
        return path
    raise FileNotFoundError("Could not find 'chromium' or 'chromium-browser' executable. Please install it.")

def setup_driver():
    """Configures and launches the headless Chrome browser."""
    print("[SETUP] Launching headless browser...")
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

def start_bot_instance():
    """Initializes the browser, logs in, and waits at the main menu."""
    global driver
    with driver_lock:
        BOT_STATE["status"] = "Starting Browser"
        driver = setup_driver()
        
        # Navigate to the game and handle initial login popups
        print("[SETUP] Navigating to Drednot.io...")
        driver.get("https://drednot.io/")
        wait = WebDriverWait(driver, 20)

        try:
            # Click "Accept" on the initial notice modal if it appears
            btn_accept = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".modal-container .btn-green")))
            driver.execute_script("arguments[0].click();", btn_accept)
            print("[SETUP] Clicked 'Accept' on notice.")
            
            # Handle login
            if ANONYMOUS_LOGIN_KEY:
                print("[SETUP] Attempting to log in with anonymous key...")
                link = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(., 'Restore old anonymous key')]")))
                driver.execute_script("arguments[0].click();", link)
                
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'div.modal-window input[maxlength="24"]'))).send_keys(ANONYMOUS_LOGIN_KEY)
                
                submit_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//div[.//h2[text()='Restore Account Key']]//button[contains(@class, 'btn-green')]")))
                driver.execute_script("arguments[0].click();", submit_btn)
                print("[SETUP] Submitted key.")
            else:
                print("[SETUP] Playing as a new guest.")
                play_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Play Anonymously')]")))
                driver.execute_script("arguments[0].click();", play_btn)

        except TimeoutException:
            print("[SETUP] Login prompts did not appear as expected. Assuming already at main menu.")
        except Exception as e:
            print(f"[ERROR] A critical error occurred during login: {e}")
            traceback.print_exc()
            driver.quit()
            return

        # Wait until we are definitely at the main menu (shipyard)
        wait.until(EC.presence_of_element_located((By.ID, 'shipyard')))
        BOT_STATE["status"] = "Idle - Awaiting Join Command"
        BOT_STATE["last_action_timestamp"] = time.time()
        print("[SYSTEM] Bot is ready and waiting at the main menu.")

# --- CORE JOIN LOGIC ---

def send_chat(message):
    """A simple helper to send a message to the in-game chat."""
    if not driver: return
    try:
        # This Javascript is more robust as it opens the chatbox if it's closed.
        driver.execute_script("""
            const msg = arguments[0];
            const chatBox = document.getElementById('chat');
            const chatInp = document.getElementById('chat-input');
            const chatBtn = document.getElementById('chat-send');
            if (chatBox && chatBox.classList.contains('closed')) {
                chatBtn.click();
            }
            if (chatInp) {
                chatInp.value = msg;
            }
            chatBtn.click();
        """, message)
    except WebDriverException as e:
        print(f"[WARN] Could not send chat message: {e.msg}")


def perform_join_ship(new_ship_id):
    """The main function to make the bot join a specific ship."""
    with driver_lock:
        if not driver:
            print("[ERROR] Join request received, but browser is not running.")
            return

        BOT_STATE["status"] = f"Joining ship {new_ship_id}..."
        BOT_STATE["last_action_timestamp"] = time.time()
        print(f"[JOIN] Attempting to join new ship: {new_ship_id}")

        try:
            # Step 1: Ensure we are at the main menu.
            try:
                driver.find_element(By.ID, "exit_button").click()
                print("[JOIN] Was in a game, clicked exit button.")
                time.sleep(1) # Give it a moment to return to menu
            except NoSuchElementException:
                print("[JOIN] Not in a game, proceeding from main menu.")

            wait = WebDriverWait(driver, 15)
            wait.until(EC.presence_of_element_located((By.ID, 'shipyard')))
            
            # Step 2: Use JavaScript to find the target ship and click it.
            # This is more reliable than multiple Selenium commands.
            # It will also click the 'refresh' button if the ship is not immediately visible.
            js_find_and_click = """
                const sid = arguments[0];
                const shipElements = Array.from(document.querySelectorAll('.sy-id'));
                const targetElement = shipElements.find(e => e.textContent === sid);
                if (targetElement) {
                    targetElement.click();
                    return true;
                }
                // If not found, click refresh and try again after a short delay
                document.querySelector('#shipyard section:nth-of-type(3) .btn-small')?.click();
                return false;
            """
            
            clicked = driver.execute_script(js_find_and_click, new_ship_id)
            if not clicked:
                time.sleep(1.5) # Wait for the list to refresh
                clicked = driver.execute_script(js_find_and_click, new_ship_id)

            if not clicked:
                raise RuntimeError(f"Could not find ship {new_ship_id} in the list after refresh.")

            # Step 3: Confirm we've joined by waiting for the in-game chat input.
            wait.until(EC.presence_of_element_located((By.ID, 'chat-input')))
            
            print(f"✅ Successfully joined ship {new_ship_id}!")
            BOT_STATE["status"] = f"In Ship: {new_ship_id}"
            BOT_STATE["current_ship_id"] = new_ship_id
            BOT_STATE["last_action_timestamp"] = time.time()
            
            time.sleep(1) # Small delay before sending message
            send_chat("Joiner bot has arrived.")

        except Exception as e:
            print(f"[ERROR] A critical error occurred while trying to join ship: {e}")
            traceback.print_exc()
            BOT_STATE["status"] = "Error during join"


# --- WEB SERVER (FLASK) ---

flask_app = Flask('')

@flask_app.route('/')
def health_check():
    """Provides a simple status page to check if the bot is running."""
    status_color = "green" if "Error" not in BOT_STATE["status"] else "red"
    html = f"""
    <html><head><title>Joiner Bot Status</title><meta http-equiv="refresh" content="5"></head>
    <body style="font-family: monospace; background-color: #121212; color: #E0E0E0;">
        <h1>Drednot.io Joiner Bot</h1>
        <p>Status: <b style="color:{status_color};">{BOT_STATE['status']}</b></p>
        <p>Current Ship: <b>{BOT_STATE['current_ship_id']}</b></p>
        <p>Last Action: {time.ctime(BOT_STATE['last_action_timestamp'])}</p>
    </body></html>
    """
    return Response(html, mimetype='text/html')

@flask_app.route('/join-request', methods=['POST'])
def handle_join_request():
    """The main endpoint that listens for requests from your Tampermonkey script."""
    # Security check
    if request.headers.get('x-api-key') != API_KEY:
        print(f"[WARN] Denied request with invalid API key from {request.remote_addr}")
        return Response('{"error": "Invalid API key"}', status=401, mimetype='application/json')

    # Data validation
    data = request.get_json()
    if not data or 'shipId' not in data:
        print(f"[WARN] Denied request with missing shipId from {request.remote_addr}")
        return Response('{"error": "Missing shipId"}', status=400, mimetype='application/json')

    new_ship_id = data['shipId']
    print(f"[SYSTEM] Received valid join request for ship: {new_ship_id}")

    # Run the join logic in a separate thread so the HTTP request can return immediately.
    # This prevents the Tampermonkey script from timing out.
    threading.Thread(target=perform_join_ship, args=(new_ship_id,)).start()

    return Response('{"status": "Join request received"}', status=200, mimetype='application/json')

def run_flask():
    """Starts the Flask web server."""
    port = int(os.environ.get("PORT", 8080)) # Use 8080 or another common port
    print(f"[SYSTEM] Web server listening for join requests on port {port}")
    flask_app.run(host='0.0.0.0', port=port)

# --- MAIN EXECUTION ---
if __name__ == "__main__":
    # Start the Flask server in a background thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # Start and manage the browser instance in the main thread
    try:
        start_bot_instance()
        # Keep the main thread alive. The bot is now driven by Flask requests.
        while True:
            time.sleep(3600) # Sleep for an hour, as no polling is needed
    except KeyboardInterrupt:
        print("\n[SYSTEM] Shutting down...")
    except Exception as e:
        print(f"\n[FATAL] A fatal error occurred in the main thread: {e}")
        traceback.print_exc()
    finally:
        if driver:
            with driver_lock:
                print("[SYSTEM] Closing browser.")
                driver.quit()
