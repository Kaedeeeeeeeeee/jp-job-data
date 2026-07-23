"""Lazy Playwright loader. Only sources that need a browser import this."""

from __future__ import annotations


_browser = None
_playwright = None


async def get_browser(headless: bool = True):
    """Return a shared Chromium browser instance, launching it on first call."""
    global _browser, _playwright
    if _browser is not None:
        return _browser
    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise RuntimeError(
            "Playwright is required for hellowork/indeed sources. "
            "Install with: pip install playwright && playwright install chromium"
        ) from e
    _playwright = await async_playwright().start()
    _browser = await _playwright.chromium.launch(headless=headless)
    return _browser


async def close_browser():
    global _browser, _playwright
    if _browser:
        await _browser.close()
        _browser = None
    if _playwright:
        await _playwright.stop()
        _playwright = None
