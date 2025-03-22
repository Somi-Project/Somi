import requests
import json
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
import pickle
import os
import re

BEARER_TOKEN = "AAAAAAAAAAAAAAAAAAAAAFQODgEAAAAAVHTp76lzh3rFzcHbmHVvQxYYpTw%3DckAlMINMjmCwxUcaXbAN4XqJVdgMJaHqNOFgPMK0zN1qLqLQCF"

class TwitterAuth:
    def __init__(self, username, password):
        self.bearer = BEARER_TOKEN
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.guest_token = None
        self.csrf_token = None
        self.COOKIE_FILE = "twitter_cookies.pkl"
        self.driver = None
        self.login_and_get_cookies()

    def login_and_get_cookies(self):
        # Set up Selenium WebDriver
        chrome_options = Options()
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        # Uncomment the line below to run in headless mode (no browser window)
        # chrome_options.add_argument("--headless")
        self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)

        try:
            # Check if cookies exist
            if os.path.exists(self.COOKIE_FILE):
                self.load_cookies()
            else:
                self.login_and_save_cookies()

            # Extract cookies for API requests
            cookies = self.driver.get_cookies()
            for cookie in cookies:
                self.session.cookies.set(cookie['name'], cookie['value'], domain=cookie.get('domain', '.twitter.com'))

            # Extract CSRF token from cookies
            self.csrf_token = self.session.cookies.get('ct0')
            if not self.csrf_token:
                raise Exception("Failed to extract CSRF token from cookies")

            # Get guest token
            self.update_guest_token()

        finally:
            if self.driver:
                self.driver.quit()

    def login_and_save_cookies(self):
        print("Logging in to Twitter...")
        self.driver.get("https://twitter.com/login")
        time.sleep(2)
        print("Entering username...")
        self.driver.find_element(By.NAME, "text").send_keys(self.username + Keys.ENTER)
        time.sleep(2)
        print("Entering password...")
        self.driver.find_element(By.NAME, "password").send_keys(self.password + Keys.ENTER)
        time.sleep(5)

        # Check if login was successful
        if "login" in self.driver.current_url.lower():
            print("Login failed. Please check your credentials or handle CAPTCHA/2FA manually.")
            print("Current URL:", self.driver.current_url)
            print("Page source snippet:", self.driver.page_source[:500])
            raise Exception("Twitter login failed. Check credentials or additional authentication steps.")

        # Save cookies
        with open(self.COOKIE_FILE, 'wb') as f:
            pickle.dump(self.driver.get_cookies(), f)
        print("Cookies saved.")

    def load_cookies(self):
        print("Loading cookies...")
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

    def update_guest_token(self):
        url = "https://api.twitter.com/1.1/guest/activate.json"
        headers = {"Authorization": f"Bearer {self.bearer}"}
        resp = self.session.post(url, headers=headers)
        if resp.status_code != 200:
            raise Exception(f"Failed to get guest token: {resp.status_code} {resp.text}")
        data = resp.json()
        self.guest_token = data.get("guest_token")
        if not self.guest_token:
            raise Exception("Failed to extract guest token from response")
        print(f"Guest token: {self.guest_token}")

    def get_headers(self):
        if not self.csrf_token or not self.guest_token:
            raise Exception("CSRF token or guest token not set. Ensure login was successful.")
        return {
            "Authorization": f"Bearer {self.bearer}",
            "Content-Type": "application/json",
            "x-guest-token": self.guest_token,
            "x-csrf-token": self.csrf_token,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Origin": "https://twitter.com",
            "Referer": "https://twitter.com/"
        }

    def get_cookies(self):
        return self.session.cookies

    def get_user_id(self, username):
        # First, try the API method
        url = "https://twitter.com/i/api/graphql/G3KGOASz96M-Qu0nwmGXNg/UserByScreenName"
        variables = {
            "screen_name": username,
            "withSafetyModeUserFields": True
        }
        features = {
            "hidden_profile_likes_enabled": True,
            "hidden_profile_subscriptions_enabled": True,
            "verified_phone_label_enabled": False,
            "subscriptions_verification_info_is_identity_verified_enabled": True,
            "responsive_web_graphql_timeline_navigation_enabled": True,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
            "responsive_web_graphql_exclude_directive_enabled": True,
            "creator_subscriptions_tweet_preview_api_enabled": True,
            "subscriptions_verification_info_verified_since_enabled": True,
            "highlights_tweets_tab_ui_enabled": True,
            "freedom_of_speech_not_reach_fetch_enabled": True,
            "standardized_nudges_misinfo": True,
            "longform_notetweets_consumption_enabled": True
        }
        params = {
            "variables": json.dumps(variables),
            "features": json.dumps(features)
        }
        resp = self.session.get(url, headers=self.get_headers(), params=params)
        if resp.status_code == 200:
            data = resp.json()
            user_id = data.get("data", {}).get("user", {}).get("result", {}).get("rest_id")
            if user_id:
                print(f"User ID fetched via API: {user_id}")
                return user_id
        print(f"API failed to get user ID: {resp.status_code} {resp.text}")

        # Fallback to Selenium if API fails
        print("Falling back to Selenium to fetch user ID...")
        chrome_options = Options()
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        # Uncomment the line below to run in headless mode
        # chrome_options.add_argument("--headless")
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
        try:
            # Load cookies
            driver.get("https://twitter.com")
            with open(self.COOKIE_FILE, 'rb') as f:
                cookies = pickle.load(f)
                for cookie in cookies:
                    driver.add_cookie(cookie)
            driver.refresh()
            time.sleep(2)

            # Navigate to the user's profile
            driver.get(f"https://twitter.com/{username}")
            time.sleep(3)

            # Scrape the user ID from the page (Twitter embeds the user ID in the page source)
            page_source = driver.page_source
            user_id_match = re.search(r'"rest_id":"(\d+)"', page_source)
            if not user_id_match:
                raise Exception("Failed to extract user ID from profile page")
            user_id = user_id_match.group(1)
            print(f"User ID fetched via Selenium: {user_id}")
            return user_id
        finally:
            driver.quit()