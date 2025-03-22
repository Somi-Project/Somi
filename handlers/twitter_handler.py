import requests
import json
import twitter_auth
import config.settings
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains

TwitterAuth = twitter_auth.TwitterAuth
TWITTER_USERNAME = config.settings.TWITTER_USERNAME
TWITTER_PASSWORD = config.settings.TWITTER_PASSWORD

class TwitterHandler:
    def __init__(self):
        # Pass username and password to TwitterAuth for Selenium login
        self.auth = TwitterAuth(TWITTER_USERNAME, TWITTER_PASSWORD)
        self.user_id = self.auth.get_user_id(TWITTER_USERNAME)

    def post(self, text):
        # First, try the API method
        url = "https://twitter.com/i/api/graphql/a1p9RWpkYKBjWv_I3WzS-A/CreateTweet"
        headers = self.auth.get_headers()
        payload = {
            "variables": {
                "tweet_text": text,
                "media": {"media_entities": [], "possibly_sensitive": False},
                "semantic_annotation_ids": [],
                "dark_request": False  # Added in case the endpoint requires this
            },
            "features": {
                "rweb_lists_timeline_redesign_enabled": True,
                "responsive_web_graphql_exclude_directive_enabled": True,
                "verified_phone_label_enabled": False,
                "creator_subscriptions_tweet_preview_api_enabled": True,
                "responsive_web_graphql_timeline_navigation_enabled": True,
                "tweetypie_unmention_optimization_enabled": True,
                "responsive_web_edit_tweet_api_enabled": True,
                "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
                "view_counts_everywhere_api_enabled": True,
                "longform_notetweets_consumption_enabled": True,
                "freedom_of_speech_not_reach_fetch_enabled": True,
                "standardized_nudges_misinfo": True,
                "longform_notetweets_rich_text_read_enabled": True,
                "responsive_web_enhance_cards_enabled": False,
                # Additional features for tweeting
                "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
                "longform_notetweets_inline_media_enabled": True
            }
        }
        resp = requests.post(url, headers=headers, json=payload, cookies=self.auth.get_cookies())
        if resp.status_code == 429:  # Rate limit handling
            reset_time = int(resp.headers.get("x-rate-limit-reset", time.time() + 60))
            wait_time = reset_time - time.time()
            time.sleep(max(wait_time, 0))
            resp = requests.post(url, headers=headers, json=payload, cookies=self.auth.get_cookies())
        if resp.status_code == 200:
            print("Tweet posted via API.")
            return "Successfully posted to Twitter!"

        # Fallback to Selenium if API fails
        print(f"API failed to post tweet: {resp.status_code} {resp.text}")
        print("Falling back to Selenium to post tweet...")
        chrome_options = Options()
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        # Uncomment the line below to run in headless mode
        # chrome_options.add_argument("--headless")
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
        try:
            # Load cookies
            driver.get("https://twitter.com")
            with open("twitter_cookies.pkl", 'rb') as f:
                cookies = pickle.load(f)
                for cookie in cookies:
                    driver.add_cookie(cookie)
            driver.refresh()
            time.sleep(2)

            # Navigate to the tweet composition page
            driver.get("https://twitter.com/compose/tweet")
            time.sleep(5)
            print("Page loaded, waiting for tweet box...")
            tweet_box = WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div[role='textbox']"))
            )
            print("Tweet box found, sending keys...")
            tweet_box.send_keys(text)
            time.sleep(2)
            print("Message entered, waiting for button...")

            # Try multiple button locators
            tweet_button = None
            locators = [
                (By.XPATH, "//button[@data-testid='tweetButton']"),
                (By.XPATH, "//button[@data-testid='tweetButtonInline']"),
                (By.XPATH, "//button[contains(text(), 'Tweet')]")
            ]
            for locator in locators:
                try:
                    tweet_button = WebDriverWait(driver, 15).until(
                        EC.element_to_be_clickable(locator)
                    )
                    print(f"Button found with locator: {locator}")
                    break
                except Exception as e:
                    print(f"Locator {locator} failed: {type(e).__name__}: {str(e)}")

            if tweet_button:
                print("Attempting automated click...")
                actions = ActionChains(driver)
                actions.move_to_element(tweet_button).click().perform()
                print("ActionChains click attempted...")
                time.sleep(5)
                if "compose/tweet" not in driver.current_url.lower():
                    print("Tweet posted successfully via Selenium.")
                    return "Successfully posted to Twitter!"
                else:
                    print("Still on compose page - auto-click failed.")
            else:
                print("No button found with any locator.")

            # Manual fallback if button not found or click fails
            print("Please click the 'Tweet' button manually within 10 seconds...")
            input("Then press Enter to continue...")
            time.sleep(5)
            if "compose/tweet" not in driver.current_url.lower():
                print("Manual post successful via Selenium.")
                return "Successfully posted to Twitter (manual click)!"
            else:
                print("Manual click didn’t work - check browser state.")
                print(f"Current URL: {driver.current_url}")
                print(f"Page source snippet: {driver.page_source[:500]}")
                return "Twitter error: Tweet not posted even after manual click."

        except Exception as e:
            print(f"Error details: {type(e).__name__}: {str(e)}")
            print(f"Current URL: {driver.current_url}")
            print(f"Page source snippet: {driver.page_source[:500]}")
            # Manual fallback on any exception
            print("Exception occurred, falling back to manual click...")
            print("Please click the 'Tweet' button manually within 10 seconds...")
            input("Then press Enter to continue...")
            time.sleep(5)
            if "compose/tweet" not in driver.current_url.lower():
                print("Manual post successful after exception.")
                return "Successfully posted to Twitter (manual click)!"
            else:
                print("Manual click didn’t work - check browser state.")
                return f"Twitter error: {type(e).__name__}: {str(e)}"
        finally:
            driver.quit()

    def fetch_mentions(self, count=5):
        url = "https://twitter.com/i/api/graphql/E4wA5vo2sjVyvpliUffSCw/UserTweetsAndReplies"
        headers = self.auth.get_headers()
        variables = {
            "userId": self.user_id,
            "count": count,
            "includePromotedContent": False,
            "withVoice": True,
            "withV2Timeline": True
        }
        features = {
            "responsive_web_graphql_exclude_directive_enabled": True,
            "verified_phone_label_enabled": False,
            "creator_subscriptions_tweet_preview_api_enabled": True,
            "responsive_web_graphql_timeline_navigation_enabled": True,
            "tweetypie_unmention_optimization_enabled": True,
            "view_counts_everywhere_api_enabled": True,
            "longform_notetweets_consumption_enabled": True,
            "freedom_of_speech_not_reach_fetch_enabled": True,
            "standardized_nudges_misinfo": True
        }
        params = {"variables": json.dumps(variables), "features": json.dumps(features)}
        resp = requests.get(url, headers=headers, params=params, cookies=self.auth.get_cookies())
        if resp.status_code != 200:
            print(f"Failed to fetch mentions: {resp.status_code} {resp.text}")
            return []
        data = resp.json()
        tweets = data.get("data", {}).get("user", {}).get("result", {}).get("timeline_v2", {}).get("timeline", {}).get("instructions", [])
        mentions = []
        for instr in tweets:
            for entry in instr.get("entries", []):
                tweet = entry.get("content", {}).get("itemContent", {}).get("tweet_results", {}).get("result", {}).get("legacy", {})
                if tweet.get("in_reply_to_user_id_str") or "@" + TWITTER_USERNAME.lower() in tweet.get("full_text", "").lower():
                    mentions.append({
                        "text": tweet.get("full_text"),
                        "username": tweet.get("in_reply_to_screen_name") or TWITTER_USERNAME,
                        "tweet_id": tweet.get("id_str")
                    })
        return mentions[:count]