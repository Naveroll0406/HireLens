"""
LinkedIn Posts scraper using Playwright.

Searches LinkedIn's Posts tab for AI-related hiring opportunities using
a persistent browser profile (reuses logged-in session) and stealth techniques.
"""

from __future__ import annotations

import asyncio
import logging
import re
import urllib.parse
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

import config
from scraper.stealth import (
    apply_stealth_scripts,
    get_launch_args,
    get_random_user_agent,
    get_random_viewport,
    human_scroll,
    human_scroll_for_duration,
    random_delay,
)
from storage.models import RawPost

logger = logging.getLogger(__name__)


class LinkedInScraper:
    """Scrapes LinkedIn Posts search results for hiring opportunities."""

    def __init__(self, profile_dir: Optional[Path] = None):
        self.profile_dir = profile_dir or config.BROWSER_PROFILE_DIR
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._playwright = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        """Launch the browser with a persistent profile."""
        self._playwright = await async_playwright().start()

        viewport = get_random_viewport()
        user_agent = get_random_user_agent()

        logger.info(
            "Launching browser (viewport: %dx%d, profile: %s)",
            viewport["width"], viewport["height"], self.profile_dir,
        )

        # Persistent context preserves cookies/login across sessions
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.profile_dir),
            headless=False,  # LinkedIn detects headless browsers aggressively
            args=get_launch_args(),
            viewport=viewport,
            user_agent=user_agent,
            locale="en-US",
            timezone_id="Asia/Kolkata",
            ignore_https_errors=True,
            java_script_enabled=True,
        )

        # Use the first page or create one
        if self._context.pages:
            self._page = self._context.pages[0]
        else:
            self._page = await self._context.new_page()

        # Apply stealth scripts
        await apply_stealth_scripts(self._page)

        logger.info("Browser started successfully.")

    async def stop(self):
        """Close the browser gracefully."""
        if self._context:
            await self._context.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("Browser closed.")

    # ------------------------------------------------------------------
    # Login check
    # ------------------------------------------------------------------

    async def ensure_logged_in(self) -> bool:
        """Check if the user is logged in to LinkedIn.

        If not logged in, navigate to login page and wait for manual login.
        Returns True if logged in, False if user cancelled.
        """
        logger.info("Checking LinkedIn login status...")
        await self._page.goto(
            "https://www.linkedin.com/feed/",
            wait_until="domcontentloaded",
            timeout=config.PAGE_TIMEOUT,
        )
        await random_delay(3, 5)

        # Check if we landed on the feed (logged in) or login page
        current_url = self._page.url

        if "/feed" in current_url:
            logger.info("✅ Already logged in to LinkedIn.")
            return True

        if "/login" in current_url or "/authwall" in current_url or "linkedin.com/uas" in current_url:
            logger.warning(
                "⚠️  Not logged in. Please log in manually in the browser window."
            )
            logger.warning("   Waiting up to 120 seconds for login...")

            # Wait for redirect to feed after manual login
            try:
                await self._page.wait_for_url(
                    "**/feed/**",
                    timeout=120_000,  # 2 minutes for manual login
                )
                logger.info("✅ Login successful!")
                await random_delay(3, 5)
                return True
            except Exception:
                logger.error("❌ Login timeout. Please try again.")
                return False

        # Unknown page — might be logged in
        logger.info("Current URL: %s — proceeding cautiously.", current_url)
        return True

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search_keyword(self, keyword: str) -> list[RawPost]:
        """Search LinkedIn Posts for a single keyword and extract results.

        Returns a list of RawPost objects.
        """
        search_url = config.LINKEDIN_SEARCH_URL_TEMPLATE.format(
            keyword=urllib.parse.quote(keyword)
        )

        logger.info("Searching: '%s'", keyword)
        logger.debug("URL: %s", search_url)

        try:
            await self._page.goto(
                search_url,
                wait_until="domcontentloaded",
                timeout=config.PAGE_TIMEOUT,
            )
        except Exception as e:
            logger.error("Failed to load search page for '%s': %s", keyword, e)
            return []

        # Wait for content to appear
        await random_delay(3, 6)

        # Check for "no results" or login wall
        page_content = await self._page.content()
        if "No results found" in page_content:
            logger.info("No results for '%s'.", keyword)
            return []

        if "/login" in self._page.url or "/authwall" in self._page.url:
            logger.error("Redirected to login page. Session may have expired.")
            return []

        # Scroll and extract in chunks to prevent LinkedIn from unmounting older posts from the virtual DOM
        all_posts = []
        seen_texts = set()
        
        scrolls_remaining = config.SCROLL_COUNT
        while scrolls_remaining > 0:
            chunk = min(3, scrolls_remaining)
            await human_scroll(
                self._page,
                times=chunk,
                min_delay=config.SCROLL_DELAY_MIN,
                max_delay=config.SCROLL_DELAY_MAX,
            )
            scrolls_remaining -= chunk
            
            current_posts = await self._extract_posts(keyword)
            for p in current_posts:
                if p.content and p.content not in seen_texts:
                    all_posts.append(p)
                    seen_texts.add(p.content)

        logger.info(
            "Found %d posts for '%s'.",
            len(all_posts), keyword,
        )

        return all_posts

    async def search_direct_url(self, url: str) -> list[RawPost]:
        """Scrape posts from a user-provided LinkedIn search URL directly.

        This allows the user to paste any LinkedIn Posts search URL
        (e.g., from their browser) and scrape results from it.
        """
        # Extract keyword from URL for tagging
        keyword_tag = "direct_url"
        try:
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(url)
            qs = parse_qs(parsed.query)
            if "keywords" in qs:
                keyword_tag = qs["keywords"][0]
        except Exception:
            pass

        logger.info("Scraping direct URL: %s", url[:80])

        try:
            await self._page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=config.PAGE_TIMEOUT,
            )
        except Exception as e:
            logger.error("Failed to load URL: %s", e)
            return []

        # Wait for content to appear
        await random_delay(5, 8)
        
        # Try to wait for any post-like container (don't fail if timeout)
        try:
            await self._page.wait_for_selector(
                "li.reusable-search__result-container, div.feed-shared-update-v2", 
                timeout=5000
            )
        except Exception:
            pass

        # Check for login wall
        if "/login" in self._page.url or "/authwall" in self._page.url:
            logger.error("Redirected to login page. Session may have expired.")
            return []

        # Check for "no results"
        page_content = await self._page.content()
        if "No results found" in page_content:
            logger.info("No results found for this URL.")
            return []

        # Read scroll duration from database settings (configurable from dashboard)
        scroll_duration = 300  # default
        try:
            from storage.database import Database
            db = Database(config.DATABASE_PATH)
            db.init_db()
            db_duration = db.get_setting("scroll_duration_seconds", "")
            db.close()
            if db_duration and int(db_duration) > 0:
                scroll_duration = int(db_duration)
        except Exception as e:
            logger.debug("Failed to read scroll_duration_seconds from DB: %s", e)

        # Scroll and extract continuously to prevent virtual DOM unmounting
        logger.info("Starting %d-second continuous scroll and extract down the posts feed...", scroll_duration)
        
        import time
        start_time = time.time()
        
        all_posts = []
        seen_texts = set()
        
        while time.time() - start_time < scroll_duration:
            # Scroll a few times (roughly 3-6 seconds)
            await human_scroll(
                self._page,
                times=3,
                min_delay=config.SCROLL_DELAY_MIN,
                max_delay=config.SCROLL_DELAY_MAX,
            )
            
            # Extract currently visible posts before LinkedIn unmounts them
            current_posts = await self._extract_posts(keyword_tag, limit=1000)
            
            # Deduplicate chunks locally
            for p in current_posts:
                if p.content and p.content not in seen_texts:
                    all_posts.append(p)
                    seen_texts.add(p.content)
                    
            elapsed = int(time.time() - start_time)
            logger.info("Scrolling... %ds elapsed of %ds. Captured %d posts so far.", elapsed, scroll_duration, len(all_posts))

        if not all_posts:
            logger.warning("No posts found. Taking debug screenshot...")
            await self.take_screenshot("no_posts_found")

        logger.info("Found %d posts from direct URL.", len(all_posts))
        return all_posts

    async def search_all_keywords(self, keywords: list[str]) -> list[RawPost]:
        """Search for all keywords with delays between searches.

        Returns combined list of all RawPosts (may contain cross-keyword duplicates,
        which the dedup module will handle).
        """
        all_posts: list[RawPost] = []

        for i, keyword in enumerate(keywords):
            try:
                posts = await self.search_keyword(keyword)
                all_posts.extend(posts)
            except Exception as e:
                logger.error("Error searching '%s': %s", keyword, e)

            # Delay between keywords (except after the last one)
            if i < len(keywords) - 1:
                delay = await self._inter_search_delay()
                logger.info(
                    "Waiting %.0fs before next search... (%d/%d keywords done)",
                    delay, i + 1, len(keywords),
                )

        logger.info(
            "Total: %d raw posts from %d keyword searches.",
            len(all_posts), len(keywords),
        )
        return all_posts

    # ------------------------------------------------------------------
    # Post extraction
    # ------------------------------------------------------------------

    async def _expand_posts(self):
        """Click all '...more' buttons on the page to expand post content."""
        try:
            logger.info("Expanding truncated posts...")
            await self._page.evaluate("""
                () => {
                    // Only query interactive elements, NOT all divs!
                    const elements = document.querySelectorAll('button, span, a');
                    for (const el of elements) {
                        // Check if the element acts as a 'see more' or 'more' button
                        const classList = (el.className || '').toString().toLowerCase();
                        // Use textContent instead of innerText to prevent massive layout recalculation lag
                        const text = (el.textContent || '').trim().toLowerCase();
                        
                        if (
                            text === 'more' || text === '...more' || text === '…more' || text === '... more' ||
                            text === 'see more' || text === '…see more' || text === '...see more' ||
                            classList.includes('see-more') || classList.includes('view-more')
                        ) {
                            try { el.click(); } catch (e) {}
                        }
                    }
                }
            """)
            await asyncio.sleep(2.0)  # Wait for DOM expansion
        except Exception as e:
            logger.debug("Failed to expand posts: %s", e)

    async def _extract_posts(self, keyword: str, limit: Optional[int] = None) -> list[RawPost]:
        """Extract post data from the current search results page."""
        await self._expand_posts()

        posts: list[RawPost] = []
        limit = limit or config.MAX_POSTS_PER_KEYWORD

        # LinkedIn post containers — try multiple selectors for resilience
        # Inject a custom class to completely bypass LinkedIn's class obfuscation
        await self._page.evaluate("""
            () => {
                const boxes = document.querySelectorAll('[data-testid="expandable-text-box"], [componentkey*="feed-commentary"], .update-components-text');
                for (const box of boxes) {
                    let container = box.closest('li.reusable-search__result-container, div[data-urn], div[data-chameleon-result-urn], div.feed-shared-update-v2, div.occludable-update, li[class*="search__result"], li');
                    
                    if (!container) {
                        let parent = box.parentElement;
                        for(let i=0; i<6; i++) {
                            if(!parent) break;
                            if (parent.querySelector('img') || parent.querySelector('a[href*="/in/"]')) {
                                container = parent;
                                break;
                            }
                            parent = parent.parentElement;
                        }
                    }
                    
                    if (container && container.tagName !== 'BODY' && container.tagName !== 'MAIN' && !container.id.includes('global-nav')) {
                        container.classList.add('hirelens-post-container');
                    }
                }
            }
        """)

        selectors = [
            ".hirelens-post-container",
            "div.feed-shared-update-v2",
            "div[data-urn*='urn:li:activity']",
            "div[data-urn*='urn:li:share']",
            "div[data-urn*='urn:li:ugcPost']",
            "li.reusable-search__result-container",
            "div.occludable-update",
            "div.search-entity",
            "div[data-chameleon-result-urn]",
            "ul.reusable-search__entity-result-list > li",
            "div.search-results__list > div",
        ]

        post_elements = []
        for selector in selectors:
            post_elements = await self._page.query_selector_all(selector)
            if post_elements:
                logger.debug(
                    "Found %d elements with selector: %s",
                    len(post_elements), selector,
                )
                break

        if not post_elements:
            # Fallback: try to get any meaningful content containers
            logger.warning("No post elements found with known selectors.")
            return await self._extract_posts_fallback(keyword, limit=limit)

        for element in post_elements[:limit]:
            try:
                post = await self._parse_post_element(element, keyword)
                if post:
                    posts.append(post)
            except Exception as e:
                logger.warning("SKIPPED: Failed to parse a post element: %s", e)
                continue

        return posts

    async def _parse_post_element(self, element, keyword: str) -> Optional[RawPost]:
        """Parse a single post element into a RawPost."""

        # --- Post URN ---
        post_urn = await element.get_attribute("data-urn") or ""
        if not post_urn:
            # Try to find a nested element with data-urn
            urn_el = await element.query_selector("[data-urn]")
            if urn_el:
                post_urn = await urn_el.get_attribute("data-urn") or ""

        # No fake URN generation — if we can't find one, leave it empty

        # --- Author name ---
        author_name = ""
        author_selectors = [
            "span.feed-shared-actor__name",
            "span.update-components-actor__name",
            ".entity-result__title-text a",
            "a.app-aware-link span[aria-hidden='true']",
        ]
        for sel in author_selectors:
            author_el = await element.query_selector(sel)
            if author_el:
                author_name = (await author_el.inner_text()).strip()
                if author_name:
                    break

        # --- Author headline ---
        author_headline = ""
        headline_selectors = [
            "span.feed-shared-actor__description",
            "span.update-components-actor__description",
            ".entity-result__primary-subtitle",
        ]
        for sel in headline_selectors:
            headline_el = await element.query_selector(sel)
            if headline_el:
                author_headline = (await headline_el.inner_text()).strip()
                if author_headline:
                    break

        # --- Post content ---
        content = ""
        content_selectors = [
            "div.feed-shared-update-v2__description",
            "div.update-components-text",
            "span.break-words",
            "div.feed-shared-text",
            "p.entity-result__summary",
        ]
        for sel in content_selectors:
            content_el = await element.query_selector(sel)
            if content_el:
                content = (await content_el.inner_text()).strip()
                if content:
                    break

        # If still no content, get full text of the element
        if not content:
            content = (await element.inner_text()).strip()

        noise_patterns = [
            r'Like\nComment\nRepost\nSend',
            r'Like\s*Comment\s*Repost\s*Send',
            r'\d+\s+reactions?',
            r'\d+\s+comments?',
            r'\d+\s+reposts?',
            r'\n\d+\n',
        ]
        import re as _re
        for pattern in noise_patterns:
            content = _re.sub(pattern, '', content, flags=_re.IGNORECASE)
        content = content.strip()

        # Skip if content is too short to be meaningful
        if len(content) < 30:
            logger.info("SKIPPED: Content too short (%d chars).", len(content))
            return None

        # --- Post URL ---
        post_url = ""
        # Try to find actual post permalink links in the element
        link_selectors = [
            "a[href*='/feed/update/']",
            "a[href*='/posts/']",
            "a[href*='urn:li:activity']",
            "a[href*='urn:li:ugcPost']",
            "a[href*='urn:li:share']",
        ]
        for link_sel in link_selectors:
            link_els = await element.query_selector_all(link_sel)
            for link_el in link_els:
                href = await link_el.get_attribute("href") or ""
                if href and not href.startswith("http"):
                    href = f"https://www.linkedin.com{href}"
                if href:
                    post_url = href
                    break
            if post_url:
                break

        # No fake URL generation — leave empty if not found

        # --- Author profile / company link (for company_url fallback) ---
        author_url = ""
        author_link_selectors = [
            "a.feed-shared-actor__container-link",
            "a.update-components-actor__container-link",
            "a.app-aware-link[href*='/company/']",
            "a.app-aware-link[href*='/in/']",
            ".entity-result__title-text a",
        ]
        for sel in author_link_selectors:
            author_link_el = await element.query_selector(sel)
            if author_link_el:
                href = await author_link_el.get_attribute("href") or ""
                if href and not href.startswith("http"):
                    href = f"https://www.linkedin.com{href}"
                if href and ("linkedin.com/company/" in href or "linkedin.com/in/" in href):
                    # Clean off tracking params
                    author_url = href.split("?")[0]
                    break

        # --- Extracted URLs from <a> elements ---
        extracted_urls: list[str] = []
        try:
            all_links = await element.query_selector_all("a[href]")
            for link in all_links:
                href = await link.get_attribute("href") or ""
                if href and href.startswith("http"):
                    if href not in extracted_urls:
                        extracted_urls.append(href)
        except Exception:
            pass

        # --- Check for author comments (if visible) to extract links ---
        try:
            # LinkedIn feed comments usually have class 'comments-comment-item' or 'feed-shared-comment'
            comments = await element.query_selector_all("article.comments-comment-item, article.comments-comments-list__comment-item")
            for comment in comments:
                commenter_el = await comment.query_selector("span.comments-post-meta__name-text, span.comments-comment-meta__description-title")
                if commenter_el:
                    commenter_name = (await commenter_el.inner_text()).strip()
                    # If commenter matches post author
                    if commenter_name and commenter_name.lower() in author_name.lower():
                        comment_links = await comment.query_selector_all("a[href]")
                        for link in comment_links:
                            href = await link.get_attribute("href") or ""
                            if href and href.startswith("http"):
                                if href not in extracted_urls:
                                    extracted_urls.append(href)
        except Exception as e:
            logger.debug("Failed to extract author comment links: %s", e)

        # --- Timestamp ---
        timestamp_text = ""
        time_selectors = [
            "span.feed-shared-actor__sub-description",
            "span.update-components-actor__sub-description",
            "time",
        ]
        for sel in time_selectors:
            time_el = await element.query_selector(sel)
            if time_el:
                timestamp_text = (await time_el.inner_text()).strip()
                if timestamp_text:
                    break

        return RawPost(
            post_urn=post_urn,
            author_name=author_name,
            author_headline=author_headline,
            content=content,
            post_url=post_url,
            author_url=author_url,
            timestamp_text=timestamp_text,
            keyword_matched=keyword,
            extracted_urls=extracted_urls,
        )

    async def _extract_posts_fallback(self, keyword: str, limit: Optional[int] = None) -> list[RawPost]:
        """Fallback extraction: grab visible text blocks that look like posts.

        Used when LinkedIn's DOM structure doesn't match known selectors.
        """
        logger.info("Using fallback extraction method...")
        posts: list[RawPost] = []
        limit = limit or config.MAX_POSTS_PER_KEYWORD

        try:
            # Tag containers dynamically via JavaScript to avoid matching the root page wrapper
            await self._page.evaluate("""
                () => {
                    const boxes = document.querySelectorAll('[data-testid="expandable-text-box"], [componentkey*="feed-commentary"], .update-components-text');
                    for (const box of boxes) {
                        let container = box.closest('li.reusable-search__result-container, div[data-urn], div[data-chameleon-result-urn], div.feed-shared-update-v2, div.occludable-update, li[class*="search__result"], li');
                        if (!container) {
                            let parent = box.parentElement;
                            for(let i=0; i<6; i++) {
                                if(!parent) break;
                                if (parent.querySelector('img') || parent.querySelector('a[href*="/in/"]')) {
                                    container = parent;
                                    break;
                                }
                                parent = parent.parentElement;
                            }
                        }
                        if (container && container.tagName !== 'BODY' && container.tagName !== 'MAIN' && !container.id.includes('global-nav')) {
                            container.classList.add('hirelens-fallback-container');
                        }
                    }
                }
            """)

            text_blocks = await self._page.query_selector_all(".hirelens-fallback-container")

            # If none found, fall back to deeper text blocks
            if not text_blocks:
                text_blocks = await self._page.query_selector_all("div.update-components-text, div[dir='ltr']")

            for block in text_blocks:
                if len(posts) >= limit:
                    break
                try:
                    text = (await block.inner_text()).strip()
                    
                    # Immediately reject if this is a giant page wrapper containing the footer
                    if "Accessibility" in text and "Talent Solutions" in text and "Community Guidelines" in text:
                        continue
                        
                    noise_patterns = [
                        r'Like\nComment\nRepost\nSend',
                        r'Like\s*Comment\s*Repost\s*Send',
                        r'\d+\s+reactions?',
                        r'\d+\s+comments?',
                        r'\d+\s+reposts?',
                        r'\n\d+\n',
                    ]
                    import re as _re
                    for pattern in noise_patterns:
                        text = _re.sub(pattern, '', text, flags=_re.IGNORECASE)
                    text = text.strip()

                    # A LinkedIn post can be short or very long. 
                    if len(text) < 30 or len(text) > 10000:
                        continue
                    if not any(kw in text.lower() for kw in [
                        "hiring", "looking", "engineer", "ai", "apply",
                        "opening", "role", "position", "developer",
                        "analyst", "data", "scientist", "manager", "specialist", "opportunity"
                    ]):
                        continue

                    # Parse basic info from the text block
                    lines = [line.strip() for line in text.split('\n') if line.strip()]
                    author = "Unknown"
                    headline = ""
                    timestamp_text = ""

                    if len(lines) > 4:
                        # Skip 'Feed post' or 'Suggested' lines
                        idx = 0
                        while idx < len(lines) and any(x in lines[idx].lower() for x in ["feed post", "suggested", "promoted", "reposted this"]):
                            idx += 1
                            
                        if idx < len(lines):
                            author = lines[idx]
                            
                            for i in range(idx + 1, min(idx + 6, len(lines))):
                                line_lower = lines[i].lower()
                                # Ignore connection degrees like '3rd+'
                                if "degree connection" in line_lower or "1st" in line_lower or "2nd" in line_lower or "3rd" in line_lower:
                                    continue
                                    
                                if '•' in lines[i] and any(x in lines[i] for x in ['h', 'd', 'm', 'w', 'mo', 'yr', 's']):
                                    timestamp_text = lines[i].replace('•', '').strip()
                                    if i > idx:
                                        headline = lines[i-1]
                                    break

                    extracted_urls = []
                    try:
                        all_links = await block.query_selector_all("a[href]")
                        for link in all_links:
                            href = await link.get_attribute("href") or ""
                            if href and href.startswith("http"):
                                if href not in extracted_urls:
                                    extracted_urls.append(href)
                    except Exception:
                        pass

                    # Look for ANY URN associated with this block
                    urn = ""
                    try:
                        # Sometimes URN is in an ancestor
                        parent = await block.evaluate_handle("el => el.closest('[data-urn]')")
                        if parent:
                            u = await parent.get_attribute("data-urn")
                            if u and ("activity" in u or "ugcPost" in u or "share" in u):
                                urn = u
                    except Exception:
                        pass
                        
                    post_url = ""
                    # Find any profile link
                    author_url = ""
                    try:
                        prof_link = await block.query_selector('a.app-aware-link[href*="/in/"], a.app-aware-link[href*="/company/"]')
                        if prof_link:
                            href = await prof_link.get_attribute("href")
                            if href:
                                author_url = href.split('?')[0]
                                if not author_url.startswith("http"):
                                    author_url = "https://www.linkedin.com" + author_url
                    except Exception:
                        pass

                    if urn and any(p.post_urn == urn for p in posts):
                        continue

                    # Deduplicate: if this block is just a child element of an already extracted post,
                    # its text will be completely contained within the parent's text.
                    is_duplicate = False
                    for existing in posts:
                        # If current text is inside an existing larger text, skip it
                        if text in existing.content:
                            is_duplicate = True
                            break
                        # If existing text is inside current larger text, replace the existing one
                        if existing.content in text:
                            posts.remove(existing)
                            break
                            
                    if is_duplicate:
                        continue

                    post = RawPost(
                        post_urn=urn,
                        author_name=author,
                        author_headline=headline,
                        content=text,
                        post_url=post_url,
                        author_url=author_url,
                        timestamp_text=timestamp_text or "Recent",
                        keyword_matched=keyword,
                        extracted_urls=extracted_urls,
                    )
                    posts.append(post)
                    logger.debug("Fallback post: urn=%s", urn[:40] if urn else "none")

                except Exception:
                    pass

        except Exception as e:
            logger.error("Fallback extraction failed: %s", e)

        logger.info("Fallback extraction found %d posts.", len(posts))
        return posts

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    async def _inter_search_delay(self) -> float:
        """Wait a random delay between keyword searches."""
        import random
        
        # Read max delay from database
        try:
            from storage.database import Database
            db = Database(config.DATABASE_PATH)
            db.init_db()
            db_delay = db.get_setting("search_delay_max", "")
            db.close()
            max_delay = float(db_delay) if db_delay else config.SEARCH_DELAY_MAX
        except Exception as e:
            logger.debug("Failed to read search_delay_max from DB: %s", e)
            max_delay = config.SEARCH_DELAY_MAX
            
        min_delay = max(5.0, max_delay - 15.0)  # Keep min somewhat reasonable
        
        delay = random.uniform(min_delay, max_delay)
        await asyncio.sleep(delay)
        return delay

    async def take_screenshot(self, name: str = "debug"):
        """Save a screenshot for debugging."""
        screenshots_dir = config.BASE_DIR / "data" / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)

        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = screenshots_dir / f"{name}_{timestamp}.png"

        await self._page.screenshot(path=str(path), full_page=True)
        logger.info("Screenshot saved: %s", path)
