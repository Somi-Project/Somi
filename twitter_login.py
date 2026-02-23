from playwright.async_api import async_playwright
import asyncio
import time
import json
import os
import random
from config.twittersettings import TWITTER_USERNAME, TWITTER_PASSWORD

class TwitterHandler:
    def __init__(self):
        self.COOKIE_FILE = "twitter_cookies.json"
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    async def initialize(self):
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
            await self.context.close()
            await self.browser.close()

    async def _is_authenticated_dom(self):
        auth_selectors = [
            "a[data-testid='AppTabBar_Home_Link']",
            "a[aria-label='Home']",
            "[data-testid='SideNav_NewTweet_Button']",
        ]
        for selector in auth_selectors:
            try:
                if await self.page.locator(selector).first.is_visible(timeout=1500):
                    return True
            except Exception:
                continue
        return False

    async def _first_visible_locator(self, selectors, timeout_ms=8000):
        for selector in selectors:
            try:
                loc = self.page.locator(selector).first
                await loc.wait_for(state="visible", timeout=timeout_ms)
                return loc
            except Exception:
                continue
        return None

    async def login_and_save_cookies(self):
        username_selectors = [
            "input[name='text']",
            "input[autocomplete='username']",
            "input[autocomplete='email']",
            "input[inputmode='text']",
        ]
        password_selectors = [
            "input[name='password']",
            "input[autocomplete='current-password']",
            "input[type='password']",
        ]
        await self.page.goto("https://x.com/i/flow/login")
        await asyncio.sleep(2)
        print("Entering username...")
        username_input = await self._first_visible_locator(username_selectors, timeout_ms=15000)
        if not username_input:
            raise RuntimeError("Username field not found")
        await username_input.click()
        await self._type_slowly(username_input, TWITTER_USERNAME)
        for next_name in ["Next", "Log in", "Next>"]:
            try:
                btn = self.page.get_by_role("button", name=next_name)
                if await btn.count() > 0:
                    await btn.first.click(timeout=3000)
                    break
            except Exception:
                continue
        await asyncio.sleep(2)
        print("Entering password...")
        password_input = await self._first_visible_locator(password_selectors, timeout_ms=20000)
        if not password_input:
            raise RuntimeError("Password field not found")
        await password_input.click()
        await self._type_slowly(password_input, TWITTER_PASSWORD + "\n")
        await asyncio.sleep(6)
        if not await self._is_authenticated_dom():
            raise RuntimeError(f"Login did not complete. URL={self.page.url}")
        cookies = await self.context.cookies()
        with open(self.COOKIE_FILE, 'w') as f:
            json.dump(cookies, f)
        print("Cookies saved.")
    async def load_cookies(self):
        await self.page.goto("https://x.com/home")
        with open(self.COOKIE_FILE, 'r') as f:
            cookies = json.load(f)
            await self.context.add_cookies(cookies)
        await self.page.goto("https://x.com/home")
        await asyncio.sleep(2)
        print("Cookies loaded.")
        if not await self._is_authenticated_dom():
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

                await self.page.goto("https://x.com/compose/tweet")
                await asyncio.sleep(5)
                print("Page loaded, waiting for tweet box...")
                tweet_box = await self.page.wait_for_selector("div[role='textbox']", timeout=15000)
                print("Tweet box found, sending keys...")
                await self._type_slowly(self.page.locator("div[role='textbox']"), message)
                await asyncio.sleep(2)
                print("Message entered, waiting for button...")

                tweet_button = None
                for selector in ["button[data-testid='tweetButton']", "button[data-testid='tweetButtonInline']"]:
                    try:
                        tweet_button = await self.page.wait_for_selector(selector, timeout=5000)
                        if tweet_button:
                            break
                    except Exception:
                        continue

                if tweet_button:
                    print("Attempting automated click...")
                    try:
                        await tweet_button.click(timeout=4000)
                    except Exception:
                        await self.page.evaluate("el => el.click()", tweet_button)
                    print("Click attempted...")
                    await asyncio.sleep(5)
                    if "compose/tweet" not in self.page.url.lower():
                        print("Tweet posted successfully.")
                        return "Successfully posted to Twitter!"
                    else:
                        print("Still on compose page - auto-click failed.")
                else:
                    print("No tweet button found via known selectors.")

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
