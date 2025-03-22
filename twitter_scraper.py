import os
import time
import logging
from pathlib import Path
import sys
import re
import random
import traceback
import json
import argparse
from playwright.async_api import async_playwright
from agents import SomiAgent
from config.settings import TWITTER_USERNAME, TWITTER_PASSWORD
import asyncio

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

class TwitterScraper:
    # Async factory method to create and initialize the scraper
    @classmethod
    async def create(cls, character_name: str):
        instance = cls(character_name)  # Creates instance synchronously
        await instance._setup_playwright()  # Sets up Playwright
        return instance  # Returns initialized scraper

    def __init__(self, character_name: str):
        if character_name is None:
            raise ValueError("Character name must be provided")
        self.playwright = None
        self.browser = None
        self.page = None
        self.cookie_file = "twitter_cookies.json"
        self.authenticated = False
        self.character_name = character_name
        self.agent = SomiAgent(character_name)  # AI agent for responses
        self.personalC_path = os.path.join("config", "personalC.json")
        if not os.path.exists(self.personalC_path):
            raise FileNotFoundError(f"personalC.json not found at {self.personalC_path}")
        with open(self.personalC_path, "r") as f:
            self.character_data = json.load(f)
        if character_name not in self.character_data:
            raise ValueError(f"Character '{character_name}' not found in {self.personalC_path}")
        self.character_params = self.character_data[character_name]

    # Sets up Playwright browser and authenticates
    async def _setup_playwright(self):
        logger.info("Setting up Playwright with Chromium.")
        try:
            self.playwright = await async_playwright().start()  # Starts Playwright
            self.browser = await self.playwright.chromium.launch(
                headless=False,  # Visible for debugging (set True for production)
                args=['--no-sandbox', '--disable-dev-shm-usage']  # Browser options
            )
            context = await self.browser.new_context(viewport={'width': 1920, 'height': 1080})
            self.page = await context.new_page()
            if os.path.exists(self.cookie_file):
                await self._load_cookies()  # Uses existing cookies
            else:
                await self._login_and_save_cookies()  # Logs in if no cookies
        except Exception as e:
            logger.error("Error setting up Playwright: %s", e)
            await self._cleanup()
            raise

    async def _load_cookies(self):
        max_retries = 3
        for attempt in range(max_retries):
            try:
                await self.page.goto("https://x.com", timeout=60000)
                with open(self.cookie_file, "r") as f:
                    cookies = json.load(f)
                    await self.page.context.add_cookies(cookies)
                await self.page.goto("https://x.com", timeout=60000)
                await asyncio.sleep(2)
                self.authenticated = True
                logger.info("Cookies loaded into Playwright.")
                break
            except Exception as e:
                logger.error("Error loading cookies (attempt %d): %s", attempt + 1, e)
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(5)

    async def _login_and_save_cookies(self):
        logger.info("No valid cookies found. Logging in...")
        max_retries = 3
        for attempt in range(max_retries):
            try:
                await self.page.goto("https://x.com/login", timeout=60000)
                await self.page.wait_for_selector("input[name='text']", timeout=15000)
                await self._type_slowly(self.page.locator("input[name='text']"), TWITTER_USERNAME + "\n")
                await self.page.wait_for_selector("input[name='password']", timeout=15000)
                await self._type_slowly(self.page.locator("input[name='password']"), TWITTER_PASSWORD + "\n")
                await self.page.wait_for_url(lambda url: "login" not in url.lower(), timeout=15000)
                cookies = await self.page.context.cookies()
                with open(self.cookie_file, 'w') as f:
                    json.dump(cookies, f)
                self.authenticated = True
                logger.info("Logged in and cookies saved.")
                break
            except Exception as e:
                logger.error("Login failed (attempt %d): %s", attempt + 1, e)
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(5)

    async def _type_slowly(self, locator, text, delay=0.1):
        for char in text:
            await locator.type(char, delay=random.uniform(delay / 2, delay * 1.5))

    # Cleans AI responses by removing mentions, hashtags, and special characters
    def _clean_response(self, response, username):
        logger.debug("Raw response from Ollama: %s", repr(response))
        response = response.strip()
        response = re.sub(r'@\w+\s*', '', response)
        response = re.sub(
            r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F700-\U0001F77F\U0001F780-\U0001F7FF\U0001F800-\U0001F8FF\U0001F900-\U0001F9FF\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF\U00002702-\U000027B0\U000024C2-\U0001F251]', 
            '', 
            response
        )
        response = re.sub(r'#\w+\s*', '', response)
        response = re.sub(r'[^a-zA-Z0-9\s.,\'-]', '', response)
        response = ' '.join(response.split())
        logger.debug("Cleaned response: %s", response)
        return response

    # Main function to scrape mentions and reply
    async def reply_to_mentions(self, limit: int = 2):
        if not self.authenticated:  # Ensures authentication before proceeding
            logger.warning("Not authenticated. Attempting to load cookies.")
            await self._load_cookies()
            if not self.authenticated:
                raise Exception("Authentication failed.")

        for mention_index in range(limit):  # Loops through specified number of mentions
            try:
                await self.page.goto("https://x.com/notifications/mentions", timeout=60000)
                await self.page.wait_for_selector("article[data-testid='tweet']", timeout=15000)
                logger.info("Mentions page loaded.")

                mentions = await self.page.query_selector_all("article[data-testid='tweet']")
                if mention_index >= len(mentions):  # Stops if no more mentions
                    logger.info("No more mentions to process.")
                    break

                logger.info("Processing mention %d.", mention_index + 1)

                # JavaScript click to open tweet (avoids profile link)
                clicked = await self.page.evaluate(
                    """(index) => {
                        const mentions = document.querySelectorAll("article[data-testid='tweet']");
                        if (index >= mentions.length) return false;
                        const mention = mentions[index];
                        const tweetText = mention.querySelector("div[data-testid='tweetText']");
                        if (tweetText) {
                            tweetText.click();
                            return true;
                        }
                        return false;
                    }""",
                    mention_index
                )
                if not clicked:
                    raise Exception("Could not find or click tweet text.")

                await self.page.wait_for_selector("div[data-testid='tweetText']", timeout=15000)
                tweet_url = self.page.url
                logger.info("Tweet page loaded. Current URL: %s", tweet_url)

                # Extracts username and tweet text
                element = await self.page.query_selector("a[role='link'][href^='/']")
                if element:
                    username = (await element.inner_text()).lstrip('@')
                else:
                    raise Exception("Could not find username element")
                
                element = await self.page.query_selector("div[data-testid='tweetText']")
                if element:
                    text = await element.inner_text()
                else:
                    raise Exception("Could not find tweet text element")
                
                logger.info("Scraped mention from @%s: %s", username, text)

                # Builds prompt with character traits for AI response
                description = self.character_params.get("description", "")
                physicality = ", ".join(self.character_params.get("physicality", []))
                memories = ", ".join(self.character_params.get("memories", []))
                inhibitions = ", ".join(self.character_params.get("inhibitions", []))
                hobbies = ", ".join(self.character_params.get("hobbies", []))
                behaviors = ", ".join(self.character_params.get("behaviors", []))

                prompt = (
                    f"You are {self.character_name}, a character with the following traits:\n"
                    f"Description: {description}\n"
                    f"Physicality: {physicality}\n"
                    f"Memories: {memories}\n"
                    f"Inhibitions: {inhibitions}\n"
                    f"Hobbies: {hobbies}\n"
                    f"Behaviors: {behaviors}\n"
                    f"Respond to the following message in under 270 characters, keeping it conversational and playful, "
                    f"reflecting your personality and traits, ensuring the response ends naturally with a complete thought or sentence, "
                    f"Do not use any special characters in your reply, message: '{text}'"
                )
                response = self.agent.generate_response(prompt)  # Generates AI reply
                reply_message = self._clean_response(response, username)  # Cleans response

                if len(reply_message) > 270:  # Truncates if over 270 characters
                    reply_message = reply_message[:270].rsplit(' ', 1)[0]

                logger.info("Generated reply: %s (length: %d)", reply_message, len(reply_message))

                # Types and posts the reply
                reply_box = await self.page.wait_for_selector("div[role='textbox']", timeout=15000)
                await reply_box.click()
                await self._type_slowly(self.page.locator("div[role='textbox']"), reply_message)
                logger.info("Typed reply: %s", reply_message)

                await asyncio.sleep(2)  # Brief delay to ensure stability
                try:
                    overlay = await self.page.query_selector("div[data-testid='sheetDialog']")
                    if overlay:
                        await self.page.evaluate("element => element.remove()", overlay)
                        logger.info("Removed overlay.")
                except:
                    logger.info("No overlay detected.")

                # Attempts native click, falls back to JavaScript
                reply_button = await self.page.wait_for_selector("//button[@data-testid='tweetButtonInline']", timeout=15000)
                try:
                    await reply_button.click()
                    logger.info("Native click attempted on reply button.")
                except Exception as e:
                    logger.warning(f"Native click failed: {str(e)}. Attempting JavaScript click.")
                    await self.page.evaluate("element => element.click()", reply_button)
                    logger.info("JavaScript click executed on reply button.")
                await asyncio.sleep(3)

                # Verifies the reply was posted
                logger.info("Verifying reply was sent...")
                await self.page.goto(tweet_url, timeout=60000)
                await self.page.wait_for_selector("div[data-testid='tweetText']", timeout=15000)
                
                reply_found = False
                replies = await self.page.query_selector_all("div[data-testid='tweetText']")
                for reply in replies:
                    if reply_message in (await reply.inner_text()):
                        reply_found = True
                        break

                if reply_found:
                    logger.info("Reply confirmed: Successfully replied to mention %d from @%s.", mention_index + 1, username)
                    print(f"Reply confirmed: Successfully replied to @%s: {reply_message}")
                else:
                    logger.warning("Reply not found: Mention not actually sent for mention %d from @%s.", mention_index + 1, username)
                    print(f"mention not actually sent for @%s")

            except Exception as e:
                logger.error("Failed to process mention %d: %s", mention_index + 1, traceback.format_exc())
                with open("debug_reply_page.html", "w", encoding="utf-8") as f:
                    f.write(await self.page.content())  # Saves page for debugging
                logger.error("Page source saved to debug_reply_page.html.")
                print(f"Error replying to mention {mention_index + 1}: {traceback.format_exc()}")

            logger.info("Returning to mentions page.")

        logger.info("Processed %d mentions.", min(limit, len(mentions)))
        await self._cleanup()  # Cleans up resources

    # Cleans up Playwright resources
    async def _cleanup(self):
        try:
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
            logger.info("Playwright resources cleaned up.")
        except Exception as e:
            logger.error("Error during cleanup: %s", e)

# Standalone script entry point
async def main():
    parser = argparse.ArgumentParser(description="Twitter Scraper for replying to mentions")
    parser.add_argument("--name", type=str, required=True, help="Name of the character to use (e.g., degenia)")
    parser.add_argument("--limit", type=int, default=2, help="Number of mentions to process")
    args = parser.parse_args()

    scraper = await TwitterScraper.create(character_name=args.name)
    try:
        await scraper.reply_to_mentions(limit=args.limit)
    except Exception as e:
        logger.error("Scraping and replying failed: %s", e)
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())