from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
import time
import pickle
import os
from config.settings import TWITTER_USERNAME, TWITTER_PASSWORD

class TwitterHandler:
    def __init__(self):
        chrome_options = Options()
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
        self.COOKIE_FILE = "twitter_cookies.pkl"
        if os.path.exists(self.COOKIE_FILE):
            self.load_cookies()
        else:
            self.login_and_save_cookies()

    def login_and_save_cookies(self):
        self.driver.get("https://twitter.com/login")
        time.sleep(2)
        print("Entering username...")
        self.driver.find_element(By.NAME, "text").send_keys(TWITTER_USERNAME + Keys.ENTER)
        time.sleep(2)
        print("Entering password...")
        self.driver.find_element(By.NAME, "password").send_keys(TWITTER_PASSWORD + Keys.ENTER)
        time.sleep(5)
        with open(self.COOKIE_FILE, 'wb') as f:
            pickle.dump(self.driver.get_cookies(), f)
        print("Cookies saved.")

    def load_cookies(self):
        self.driver.get("https://twitter.com")
        with open(self.COOKIE_FILE, 'rb') as f:
            cookies = pickle.load(f)
            for cookie in cookies:
                self.driver.add_cookie(cookie)
        self.driver.refresh()
        time.sleep(2)
        print("Cookies loaded.")
        if "login" in self.driver.current_url.lower():
            print("Cookies invalid, re-logging in...")
            self.login_and_save_cookies()

    def post(self, message):
        try:
            self.driver.get("https://twitter.com/compose/tweet")
            time.sleep(5)
            print("Page loaded, waiting for tweet box...")
            tweet_box = WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div[role='textbox']"))
            )
            print("Tweet box found, sending keys...")
            tweet_box.send_keys(message)
            time.sleep(2)
            print("Message entered, waiting for button...")

            # Try multiple button locators
            tweet_button = None
            locators = [
                (By.XPATH, "//button[@data-testid='tweetButton']"),  # Original working locator
                (By.XPATH, "//button[@data-testid='tweetButtonInline']"),  # Alternative
                (By.XPATH, "//button[contains(text(), 'Tweet')]")  # Text-based fallback
            ]
            for locator in locators:
                try:
                    tweet_button = WebDriverWait(self.driver, 15).until(
                        EC.element_to_be_clickable(locator)
                    )
                    print(f"Button found with locator: {locator}")
                    break
                except Exception as e:
                    print(f"Locator {locator} failed: {type(e).__name__}: {str(e)}")

            if tweet_button:
                print("Attempting automated click...")
                actions = ActionChains(self.driver)
                actions.move_to_element(tweet_button).click().perform()
                print("ActionChains click attempted...")
                time.sleep(5)
                if "compose/tweet" not in self.driver.current_url.lower():
                    print("Tweet posted successfully.")
                    return "Successfully posted to Twitter!"
                else:
                    print("Still on compose page - auto-click failed.")
            else:
                print("No button found with any locator.")

            # Manual fallback if button not found or click fails
            print("Please click the 'Tweet' button manually within 10 seconds...")
            input("Then press Enter to continue...")
            time.sleep(5)
            if "compose/tweet" not in self.driver.current_url.lower():
                print("Manual post successful.")
                return "Successfully posted to Twitter (manual click)!"
            else:
                print("Manual click didn’t work - check browser state.")
                print(f"Current URL: {self.driver.current_url}")
                print(f"Page source snippet: {self.driver.page_source[:500]}")
                return "Twitter error: Tweet not posted even after manual click."

        except Exception as e:
            print(f"Error details: {type(e).__name__}: {str(e)}")
            print(f"Current URL: {self.driver.current_url}")
            print(f"Page source snippet: {self.driver.page_source[:500]}")
            # Manual fallback on any exception
            print("Exception occurred, falling back to manual click...")
            print("Please click the 'Tweet' button manually within 10 seconds...")
            input("Then press Enter to continue...")
            time.sleep(5)
            if "compose/tweet" not in self.driver.current_url.lower():
                print("Manual post successful after exception.")
                return "Successfully posted to Twitter (manual click)!"
            else:
                print("Manual click didn’t work - check browser state.")
                return f"Twitter error: {type(e).__name__}: {str(e)}"
        finally:
            self.driver.quit()

if __name__ == "__main__":
    handler = TwitterHandler()
    result = handler.post("Test tweet from MissNovel90s! #90sRealTalk")
    print(result)