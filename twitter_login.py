from playwright.async_api import async_playwright
import asyncio
import time
import json
import os
import random
from config.settings import TWITTER_USERNAME, TWITTER_PASSWORD

class TwitterHandler:
    def __init__(self):
        self.COOKIE_FILE = "twitter_cookies.json"
        # Initialize in an async method since __init__ cannot be async
        asyncio.run(self._initialize())

    async def _initialize(self):
        async with async_playwright() as playwright:
            self.playwright = playwright
            self.browser = await playwright.chromium.launch(
                headless=False,
                args=['--no-sandbox', '--disable-dev-shm-usage']
            )
            self.context = await self.browser.new_context(viewport={'width': 1920, 'height': 1080})
            self.page = await self.context.new_page()
            if os.path.exists(self.COOKIE_FILE):
                await self.load_cookies()
            else:
                await self.login_and_save_cookies()
            # Close resources after initialization
            await self.context.close()
            await self.browser.close()

    async def login_and_save_cookies(self):
        await self.page.goto("https://twitter.com/login")
        await asyncio.sleep(2)
        print("Entering username...")
        await self._type_slowly(self.page.locator("input[name='text']"), TWITTER_USERNAME + "\n")
        await asyncio.sleep(2)
        print("Entering password...")
        await self._type_slowly(self.page.locator("input[name='password']"), TWITTER_PASSWORD + "\n")
        await asyncio.sleep(5)
        cookies = await self.context.cookies()
        with open(self.COOKIE_FILE, 'w') as f:
            json.dump(cookies, f)
        print("Cookies saved.")

    async def load_cookies(self):
        await self.page.goto("https://twitter.com")
        with open(self.COOKIE_FILE, 'r') as f:
            cookies = json.load(f)
            await self.context.add_cookies(cookies)
        await self.page.goto("https://twitter.com")
        await asyncio.sleep(2)
        print("Cookies loaded.")
        if "login" in self.page.url.lower():
            print("Cookies invalid, re-logging in...")
            await self.login_and_save_cookies()

    async def _type_slowly(self, locator, text, delay=0.1):
        for char in text:
            await locator.type(char, delay=random.uniform(delay / 2, delay * 1.5))

    async def post(self, message):
        async with async_playwright() as playwright:
            self.playwright = playwright
            self.browser = await playwright.chromium.launch(
                headless=False,
                args=['--no-sandbox', '--disable-dev-shm-usage']
            )
            self.context = await self.browser.new_context(viewport={'width': 1920, 'height': 1080})
            self.page = await self.context.new_page()
            try:
                # Load cookies if they exist
                if os.path.exists(self.COOKIE_FILE):
                    await self.load_cookies()
                else:
                    await self.login_and_save_cookies()

                await self.page.goto("https://twitter.com/compose/tweet")
                await asyncio.sleep(5)
                print("Page loaded, waiting for tweet box...")
                tweet_box = await self.page.wait_for_selector("div[role='textbox']", timeout=15000)
                print("Tweet box found, sending keys...")
                await self._type_slowly(self.page.locator("div[role='textbox']"), message)
                await asyncio.sleep(2)
                print("Message entered, waiting for button...")

                tweet_button = await self.page.wait_for_selector("//button[@data-testid='tweetButton']", timeout=15000)
                if tweet_button:
                    print("Attempting automated click...")
                    await tweet_button.click()
                    print("Click attempted...")
                    await asyncio.sleep(5)
                    if "compose/tweet" not in self.page.url.lower():
                        print("Tweet posted successfully.")
                        return "Successfully posted to Twitter!"
                    else:
                        print("Still on compose page - auto-click failed.")
                else:
                    print("No button found.")

                print("Please click the 'Tweet' button manually within 10 seconds...")
                input("Then press Enter to continue...")
                await asyncio.sleep(5)
                if "compose/tweet" not in self.page.url.lower():
                    print("Manual post successful.")
                    return "Successfully posted to Twitter (manual click)!"
                else:
                    print("Manual click didn’t work - check browser state.")
                    return "Twitter error: Tweet not posted even after manual click."

            except Exception as e:
                print(f"Error details: {type(e).__name__}: {str(e)}")
                return f"Twitter error: {type(e).__name__}: {str(e)}"
            finally:
                await self.context.close()
                await self.browser.close()

if __name__ == "__main__":
    async def main():
        handler = TwitterHandler()
        result = await handler.post("Test tweet from MissNovel90s! #90sRealTalk")
        print(result)

    asyncio.run(main())