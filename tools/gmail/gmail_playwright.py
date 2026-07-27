import sys
import json
import os
import urllib.parse
from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

PROFILE_DIR = os.path.join(os.path.dirname(__file__), "chrome_profile")
APPS_SCRIPT_URL = "https://script.google.com/a/macros/avaya.com/s/AKfycbwfqUGLMBppaPEtdzAC74_TeT34shpYkIVv5FMY1JjhqPDH0MXEp-WdeTOp8zmCDL0F/exec"

def setup_login():
    print("\n=======================================================")
    print("[One-Time Setup] Opening browser for Avaya SSO login...")
    print("1. Complete your sign-in in the opened browser window.")
    print("2. Once signed in, press ENTER in this terminal.")
    print("=======================================================\n")
    
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=False,
            args=["--disable-blink-features=AutomationControlled"]
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(APPS_SCRIPT_URL + "?action=search&q=is:unread")
        
        try:
            input(">>> Press ENTER in this terminal after you finish signing in: ")
        except KeyboardInterrupt:
            print("\nSetup cancelled.")
            try:
                context.close()
            except Exception:
                pass
            return

        # Defensive: if the user closed the browser window / SSO tab BEFORE pressing
        # ENTER, the page target is gone and page.text_content("body") raises
        # TargetClosedError, which aborts the script before context.close() runs and
        # loses the freshly-saved SSO cookies. Guard both the inspection and the close.
        try:
            if not page.is_closed():
                body_text = page.text_content("body")
        except Exception:
            pass
        print("\nLogin saved successfully! Session active.")
        try:
            context.close()
        except Exception:
            pass

def query_apps_script(action, extra_params=""):
    url = f"{APPS_SCRIPT_URL}?action={action}{extra_params}"
    
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(url)
        page.wait_for_load_state("networkidle")
        body_text = page.text_content("body")
        context.close()
        return body_text

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "login":
        setup_login()
        sys.exit(0)

    if len(sys.argv) < 2:
        print("Usage: python gmail_playwright.py <login|search|read|send> [args...]")
        sys.exit(1)
        
    action = sys.argv[1]
    if action == "search":
        q = sys.argv[2] if len(sys.argv) > 2 else "is:unread"
        res = query_apps_script("search", f"&q={urllib.parse.quote(q)}")
        print(res)
    elif action == "read":
        msg_id = sys.argv[2] if len(sys.argv) > 2 else ""
        res = query_apps_script("read", f"&id={msg_id}")
        print(res)
    elif action == "send":
        to = sys.argv[2]
        subject = sys.argv[3]
        body = sys.argv[4]
        res = query_apps_script("send", f"&to={urllib.parse.quote(to)}&subject={urllib.parse.quote(subject)}&body={urllib.parse.quote(body)}")
        print(res)
