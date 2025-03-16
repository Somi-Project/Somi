# handlers/twitter.py
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import pickle
import os
from config.settings import TWITTER_USERNAME, TWITTER_PASSWORD

class TwitterHandler:
    def __init__(self):
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-gpu")
        self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
        self.cookie_file = "twitter_cookies.pkl"
        if os.path.exists(self.cookie_file):
            self.load_cookies()
        else:
            self.login_and_save_cookies()

    def login_and_save_cookies(self):
        self.driver.get("https://twitter.com/login")
        time.sleep(2)
        self.driver.find_element(By.NAME, "text").send_keys(TWITTER_USERNAME + Keys.ENTER)
        time.sleep(2)
        self.driver.find_element(By.NAME, "password").send_keys(TWITTER_PASSWORD + Keys.ENTER)
        time.sleep(5)
        with open(self.cookie_file, 'wb') as f:
            pickle.dump(self.driver.get_cookies(), f)
        print("Cookies saved.")

    def load_cookies(self):
        self.driver.get("https://twitter.com")
        with open(self.cookie_file, 'rb') as f:
            cookies = pickle.load(f)
            for cookie in cookies:
                self.driver.add_cookie(cookie)
        self.driver.refresh()
        time.sleep(2)
        print("Cookies loaded.")

    def post(self, message):
        try:
            self.driver.get("https://twitter.com/compose/tweet")
            time.sleep(2)
            tweet_box = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div[role='textbox']"))
            )
            tweet_box.send_keys(message)
            tweet_button = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//button[@data-testid='tweetButton']"))
            )
            # Try direct click, fall back to JavaScript
            try:
                tweet_button.click()
            except Exception:
                self.driver.execute_script("arguments[0].click();", tweet_button)
            time.sleep(2)
            return "Successfully posted to Twitter!"
        except Exception as e:
            return f"Twitter error: {str(e)}"
        finally:
            self.driver.quit()