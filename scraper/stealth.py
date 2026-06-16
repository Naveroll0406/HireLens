"""
Anti-detection and stealth utilities for Playwright-based scraping.

Applies browser fingerprint masking, human-like behavior simulation,
and randomization to reduce detection risk on LinkedIn.
"""

from __future__ import annotations

import logging
import random
from typing import Optional

from playwright.async_api import BrowserContext, Page

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# User agents — realistic Chrome on Windows
# --------------------------------------------------------------------------
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
]

# --------------------------------------------------------------------------
# Viewport sizes — common desktop resolutions
# --------------------------------------------------------------------------
VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
    {"width": 1680, "height": 1050},
]


def get_random_user_agent() -> str:
    """Return a random realistic user agent string."""
    return random.choice(USER_AGENTS)


def get_random_viewport() -> dict:
    """Return a random common viewport size."""
    return random.choice(VIEWPORTS)


def get_launch_args() -> list[str]:
    """Return Chromium launch arguments for stealth."""
    return [
        "--disable-blink-features=AutomationControlled",
        "--disable-features=IsolateOrigins,site-per-process",
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--disable-accelerated-2d-canvas",
        "--disable-gpu",
        "--lang=en-US,en",
    ]


async def apply_stealth_scripts(page: Page):
    """Inject JavaScript to hide automation signals."""

    # Override navigator.webdriver
    await page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined,
        });
    """)

    # Override navigator.plugins (empty in headless)
    await page.add_init_script("""
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5],
        });
    """)

    # Override navigator.languages
    await page.add_init_script("""
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en'],
        });
    """)

    # Mask Chrome runtime
    await page.add_init_script("""
        window.chrome = {
            runtime: {},
        };
    """)

    # Override permissions API
    await page.add_init_script("""
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) =>
            parameters.name === 'notifications'
                ? Promise.resolve({ state: Notification.permission })
                : originalQuery(parameters);
    """)

    logger.debug("Stealth scripts applied to page.")


async def random_delay(min_sec: float = 1.0, max_sec: float = 3.0):
    """Sleep for a random duration to simulate human behavior."""
    import asyncio
    delay = random.uniform(min_sec, max_sec)
    await asyncio.sleep(delay)


async def human_scroll(page: Page, times: int = 3,
                       min_delay: float = 2.0, max_delay: float = 5.0):
    """Scroll down the page in a human-like manner.

    Uses smooth scrolling so the user can see the page moving in the
    Chromium window.  Also scrolls LinkedIn's inner container when the
    main window scroll has no effect.
    """
    for i in range(times):
        # Variable scroll distance (300-800 pixels)
        scroll_distance = random.randint(300, 800)

        # Smooth scroll — try window first, then inner container
        await page.evaluate(f"""
            (() => {{
                const d = {scroll_distance};
                // Try the main scrollable container LinkedIn uses
                const container = document.querySelector('.search-results-container')
                    || document.querySelector('main')
                    || document.querySelector('.scaffold-layout__main');
                if (container && container.scrollHeight > container.clientHeight) {{
                    container.scrollBy({{ top: d, behavior: 'smooth' }});
                }}
                window.scrollBy({{ top: d, behavior: 'smooth' }});
            }})()
        """)

        # Random pause between scrolls
        await random_delay(min_delay, max_delay)

        # Occasionally scroll up a tiny bit (human behavior)
        if random.random() < 0.2:
            up_scroll = random.randint(50, 150)
            await page.evaluate(f"""
                (() => {{
                    const d = {up_scroll};
                    const container = document.querySelector('.search-results-container')
                        || document.querySelector('main')
                        || document.querySelector('.scaffold-layout__main');
                    if (container && container.scrollHeight > container.clientHeight) {{
                        container.scrollBy({{ top: -d, behavior: 'smooth' }});
                    }}
                    window.scrollBy({{ top: -d, behavior: 'smooth' }});
                }})()
            """)
            await random_delay(0.5, 1.5)

        logger.debug("Scroll %d/%d: %dpx down", i + 1, times, scroll_distance)


async def human_type(page: Page, selector: str, text: str,
                     min_delay_ms: int = 50, max_delay_ms: int = 150):
    """Type text with human-like keystroke delays."""
    element = page.locator(selector)
    await element.click()
    await random_delay(0.3, 0.8)

    for char in text:
        await element.press(char)
        delay_ms = random.randint(min_delay_ms, max_delay_ms)
        import asyncio
        await asyncio.sleep(delay_ms / 1000.0)

async def human_scroll_for_duration(page: Page, duration_seconds: int,
                                    min_delay: float = 2.0, max_delay: float = 4.0):
    """Scroll down the page continuously for a set duration.

    Uses smooth scrolling so motion is visible in the Chromium window.
    Also scrolls LinkedIn's inner scrollable container.
    """
    import time
    start_time = time.time()
    scroll_count = 0

    logger.info("Starting continuous smooth scroll for %d seconds...", duration_seconds)

    while time.time() - start_time < duration_seconds:
        # Scroll distance
        scroll_distance = random.randint(400, 1000)
        await page.evaluate(f"""
            (() => {{
                const d = {scroll_distance};
                const container = document.querySelector('.search-results-container')
                    || document.querySelector('main')
                    || document.querySelector('.scaffold-layout__main');
                if (container && container.scrollHeight > container.clientHeight) {{
                    container.scrollBy({{ top: d, behavior: 'smooth' }});
                }}
                window.scrollBy({{ top: d, behavior: 'smooth' }});
            }})()
        """)
        scroll_count += 1

        # Pause
        await random_delay(min_delay, max_delay)

        # Occasional up-scroll
        if random.random() < 0.15:
            up_scroll = random.randint(100, 300)
            await page.evaluate(f"""
                (() => {{
                    const d = {up_scroll};
                    const container = document.querySelector('.search-results-container')
                        || document.querySelector('main')
                        || document.querySelector('.scaffold-layout__main');
                    if (container && container.scrollHeight > container.clientHeight) {{
                        container.scrollBy({{ top: -d, behavior: 'smooth' }});
                    }}
                    window.scrollBy({{ top: -d, behavior: 'smooth' }});
                }})()
            """)
            await random_delay(0.5, 1.5)

        elapsed = int(time.time() - start_time)
        if scroll_count % 10 == 0:
            logger.info("Scrolling... %ds elapsed of %ds", elapsed, duration_seconds)

    logger.info("Finished scrolling after %d seconds (%d scrolls).", duration_seconds, scroll_count)
