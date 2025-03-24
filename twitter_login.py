from playwright.sync_api import sync_playwright
import time
import json
import os
import random
from config.settings import TWITTER_USERNAME, TWITTER_PASSWORD

class TwitterHandler:
    def __init__(self):
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(
            headless=False,
            args=['--no-sandbox', '--disable-dev-shm-usage']
        )
        self.context = self.browser.new_context(viewport={'width': 1920, 'height': 1080})
        self.page = self.context.new_page()
        self.COOKIE_FILE = "twitter_cookies.json"
        if os.path.exists(self.COOKIE_FILE):
            self.load_cookies()
        else:
            self.login_and_save_cookies()

    def login_and_save_cookies(self):
        self.page.goto("https://twitter.com/login")
        time.sleep(2)
        print("Entering username...")
        self._type_slowly(self.page.locator("input[name='text']"), TWITTER_USERNAME + "\n")
        time.sleep(2)
        print("Entering password...")
        self._type_slowly(self.page.locator("input[name='password']"), TWITTER_PASSWORD + "\n")
        time.sleep(5)
        cookies = self.context.cookies()
        with open(self.COOKIE_FILE, 'w') as f:
            json.dump(cookies, f)
        print("Cookies saved.")

    def load_cookies(self):
        self.page.goto("https://twitter.com")
        with open(self.COOKIE_FILE, 'r') as f:
            cookies = json.load(f)
            self.context.add_cookies(cookies)
        self.page.goto("https://twitter.com")
        time.sleep(2)
        print("Cookies loaded.")
        if "login" in self.page.url.lower():
            print("Cookies invalid, re-logging in...")
            self.login_and_save_cookies()

    def _type_slowly(self, locator, text, delay=0.1):
        for char in text:
            locator.type(char, delay=random.uniform(delay / 2, delay * 1.5))

    def post(self, message):
        try:
            self.page.goto("https://twitter.com/compose/tweet")
            time.sleep(5)
            print("Page loaded, waiting for tweet box...")
            tweet_box = self.page.wait_for_selector("div[role='textbox']", timeout=15000)
            print("Tweet box found, sending keys...")
            self._type_slowly(self.page.locator("div[role='textbox']"), message)
            time.sleep(2)
            print("Message entered, waiting for button...")

            tweet_button = self.page.wait_for_selector("//button[@data-testid='tweetButton']", timeout=15000)
            if tweet_button:
                print("Attempting automated click...")
                tweet_button.click()
                print("Click attempted...")
                time.sleep(5)
                if "compose/tweet" not in self.page.url.lower():
                    print("Tweet posted successfully.")
                    return "Successfully posted to Twitter!"
                else:
                    print("Still on compose page - auto-click failed.")
            else:
                print("No button found.")

            print("Please click the 'Tweet' button manually within 10 seconds...")
            input("Then press Enter to continue...")
            time.sleep(5)
            if "compose/tweet" not in self.page.url.lower():
                print("Manual post successful.")
                return "Successfully posted to Twitter (manual click)!"
            else:
                print("Manual click didn’t work - check browser state.")
                return f"Twitter error: Tweet not posted even after manual click."

        except Exception as e:
            print(f"Error details: {type(e).__name__}: {str(e)}")
            return f"Twitter error: {type(e).__name__}: {str(e)}"
        finally:
            self.browser.close()
            self.playwright.stop()

if __name__ == "__main__":
    handler = TwitterHandler()
    result = handler.post("Test tweet from MissNovel90s! #90sRealTalk")
    print(result)