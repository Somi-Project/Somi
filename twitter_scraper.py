import os
import time
import logging
from pathlib import Path
import sys
import re
import random
import traceback
import selenium
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
import pickle
from agents import SomiAgent
from config.settings import TWITTER_USERNAME, TWITTER_PASSWORD

# Set up logging without Chrome warnings
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)
options = webdriver.ChromeOptions()
options.add_experimental_option('excludeSwitches', ['enable-logging'])

class TwitterScraper:
    def __init__(self, use_selenium: bool = True):
        self.driver = None
        self.cookie_file = "twitter_cookies.pkl"
        self.authenticated = False
        self.agent = SomiAgent("MissNovel90s")
        self.use_selenium = use_selenium
        if self.use_selenium:
            self._setup_selenium()

    def _setup_selenium(self):
        logger.info("Setting up Selenium WebDriver.")
        try:
            chrome_options = Options()
            chrome_options.add_argument("--headless")  # Using headless mode
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--window-size=1920,1080")
            chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
            self.driver = webdriver.Chrome(options=chrome_options)
            if os.path.exists(self.cookie_file):
                self._load_cookies()
            else:
                self._login_and_save_cookies()
        except Exception as e:
            logger.error("Error setting up Selenium: %s", e)
            sys.exit(1)

    def _load_cookies(self):
        try:
            self.driver.get("https://x.com")
            with open(self.cookie_file, "rb") as f:
                cookies = pickle.load(f)
                for cookie in cookies:
                    self.driver.add_cookie(cookie)
            self.driver.refresh()
            time.sleep(2)
            self.authenticated = True
            logger.info("Cookies loaded into Selenium.")
        except Exception as e:
            logger.error("Error loading cookies: %s", e)
            self._login_and_save_cookies()

    def _login_and_save_cookies(self):
        logger.info("No valid cookies found. Logging in...")
        try:
            self.driver.get("https://x.com/login")
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.NAME, "text"))
            ).send_keys(TWITTER_USERNAME + Keys.ENTER)
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.NAME, "password"))
            ).send_keys(TWITTER_PASSWORD + Keys.ENTER)
            WebDriverWait(self.driver, 15).until(
                lambda d: "login" not in d.current_url.lower()
            )
            with open(self.cookie_file, 'wb') as f:
                pickle.dump(self.driver.get_cookies(), f)
            self.authenticated = True
            logger.info("Logged in and cookies saved.")
        except Exception as e:
            logger.error("Login failed: %s", e)
            sys.exit(1)

    def reply_to_mentions(self, limit: int = 5):
        if not self.use_selenium:
            logger.error("This method requires Selenium. Set use_selenium=True.")
            return

        if not self.authenticated:
            logger.warning("Not authenticated. Attempting to load cookies.")
            self._load_cookies()
            if not self.authenticated:
                raise Exception("Authentication failed. Cookies not loaded or invalid.")

        self.driver.get("https://x.com/notifications/mentions")
        WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "article"))
        )
        logger.info("Mentions page loaded.")

        for i in range(min(limit, 5)):
            try:
                mentions = self.driver.find_elements(By.CSS_SELECTOR, "article[data-testid='tweet']")
                if i >= len(mentions):
                    logger.info("No more mentions to process.")
                    break

                mention = mentions[i]
                logger.info("Processing mention %d.", i + 1)

                mention.click()
                WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div[role='textbox'][data-testid='tweetTextarea_0']"))
                )
                logger.info("Clicked mention %d.", i + 1)

                username = self.driver.find_element(By.CSS_SELECTOR, "a[role='link'][href^='/']").text.lstrip('@')
                text = self.driver.find_element(By.CSS_SELECTOR, "div[data-testid='tweetText']").text
                logger.info("Mention from @%s: %s", username, text)

                prompt = f"Reply to this tweet mentioning you: @{username} said '{text}'"
                response = self.agent.generate_response(prompt)
                reply_message = f"@{username} {response}"

                # Enforce Twitter's 280-character limit
                MAX_CHARS = 280
                if len(reply_message) > MAX_CHARS:
                    reply_message = reply_message[:MAX_CHARS - 3] + "..."  # Truncate and add ellipsis
                    logger.warning("Reply truncated to %d characters to fit Twitter limit.", MAX_CHARS)

                reply_box = self.driver.find_element(By.CSS_SELECTOR, "div[role='textbox'][data-testid='tweetTextarea_0']")
                reply_box.click()
                reply_box.send_keys(reply_message)
                logger.info("Entered reply: %s", reply_message)

                time.sleep(10)

                reply_button = WebDriverWait(self.driver, 20).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[@data-testid='tweetButtonInline']"))
                )

                # Simulate hover before clicking
                actions = ActionChains(self.driver)
                actions.move_to_element(reply_button).perform()
                logger.info("Hovered over reply button for @%s.", username)

                # Try direct click, fall back to JavaScript
                try:
                    reply_button.click()
                except Exception:
                    self.driver.execute_script("arguments[0].click();", reply_button)
                logger.info("Reply button clicked for @%s.", username)

                time.sleep(2)
                if "status" in self.driver.current_url.lower():
                    logger.info("Successfully replied to @%s.", username)
                    print(f"Replied to @{username}: {reply_message}")
                else:
                    logger.warning("Reply may not have posted for @%s. Still on same page.", username)

                self.driver.get("https://x.com/notifications/mentions")
                WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.TAG_NAME, "article"))
                )
                logger.info("Returned to mentions page.")

            except Exception as e:
                # Debug: Save page source if button not found
                if isinstance(e, selenium.common.exceptions.TimeoutException):
                    with open("debug_reply_page.html", "w", encoding="utf-8") as f:
                        f.write(self.driver.page_source)
                    logger.error("Page source saved to debug_reply_page.html for inspection.")
                logger.error("Failed to process mention %d: %s", i + 1, traceback.format_exc())
                print(f"Error replying to mention {i + 1}: {traceback.format_exc()}")
                self.driver.get("https://x.com/notifications/mentions")
                WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.TAG_NAME, "article"))
                )
                logger.info("Continuing to next mention after error.")

        logger.info("Processed %d mentions.", min(limit, len(mentions)))

    def __del__(self):
        if self.driver:
            self.driver.quit()
            logger.info("Selenium WebDriver closed.")

def main():
    scraper = TwitterScraper(use_selenium=True)
    try:
        scraper.reply_to_mentions(limit=2)
    except Exception as e:
        logger.error("Scraping and replying failed: %s", e)
        sys.exit(1)

if __name__ == "__main__":
    main()