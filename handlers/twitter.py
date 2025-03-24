import os
import json
import asyncio
import logging
from playwright.async_api import async_playwright
from config.settings import TWITTER_USERNAME, TWITTER_PASSWORD

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

class TwitterHandler:
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.cookie_file = "twitter_cookies.json"

    async def initialize(self):
        try:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=False,
                args=['--no-sandbox', '--disable-dev-shm-usage']
            )
            self.context = await self.browser.new_context(viewport={'width': 1920, 'height': 1080})
            self.page = await self.context.new_page()
            if os.path.exists(self.cookie_file):
                await self._load_cookies()
            else:
                await self._login_and_save_cookies()
        except Exception as e:
            logger.error(f"Error initializing Playwright: {str(e)}")
            await self._cleanup()
            raise

    async def _load_cookies(self):
        max_retries = 3
        for attempt in range(max_retries):
            try:
                with open(self.cookie_file, 'r') as f:
                    cookies = json.load(f)
                await self.context.add_cookies(cookies)
                await self.page.goto("https://x.com", timeout=60000)
                logger.info("Cookies loaded successfully.")
                break
            except Exception as e:
                logger.error(f"Error loading cookies (attempt {attempt + 1}): {str(e)}")
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(5)

    async def _login_and_save_cookies(self):
        logger.info("No cookies found. Logging in...")
        max_retries = 3
        for attempt in range(max_retries):
            try:
                await self.page.goto("https://x.com/login", timeout=60000)
                await self.page.wait_for_selector("input[name='text']", timeout=15000)
                await self.page.locator("input[name='text']").type(TWITTER_USERNAME + "\n")
                await self.page.wait_for_selector("input[name='password']", timeout=15000)
                await self.page.locator("input[name='password']").type(TWITTER_PASSWORD + "\n")
                await self.page.wait_for_url(lambda url: "login" not in url.lower(), timeout=15000)
                cookies = await self.context.cookies()
                with open(self.cookie_file, 'w') as f:
                    json.dump(cookies, f)
                logger.info("Logged in and cookies saved.")
                break
            except Exception as e:
                logger.error(f"Login failed (attempt {attempt + 1}): {str(e)}")
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(5)

    async def post(self, message):
        try:
            if not self.page:
                await self.initialize()
            await self.page.goto("https://x.com/home", timeout=60000)
            await self.page.wait_for_selector("div[role='textbox']", timeout=15000)
            await self.page.locator("div[role='textbox']").click()
            await self.page.locator("div[role='textbox']").type(message)
            await asyncio.sleep(1)
            post_button = await self.page.wait_for_selector(
                "//button[@data-testid='tweetButtonInline']", timeout=15000
            )
            for attempt in range(2):
                try:
                    await post_button.click(timeout=5000)
                    logger.info(f"Native click succeeded on attempt {attempt + 1}.")
                    break
                except Exception as e:
                    logger.warning(f"Native click failed on attempt {attempt + 1}: {str(e)}")
                    if attempt == 0:
                        await asyncio.sleep(1)
                    else:
                        logger.info("Falling back to JavaScript click.")
                        await self.page.evaluate("element => element.click()", post_button)
                        logger.info("JavaScript click executed on post button.")
            await asyncio.sleep(3)
            return "Successfully posted to Twitter!"
        except Exception as e:
            logger.error(f"Error posting tweet: {str(e)}")
            return f"Failed to post tweet: {str(e)}"
        finally:
            await self._cleanup()

    async def _cleanup(self):
        try:
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
            logger.info("Playwright resources cleaned up.")
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")