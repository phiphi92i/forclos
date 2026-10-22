"""Render an HTML page at 1920x1080 to a 4K PNG (2x), after its web fonts and images have loaded.
Usage: python render.py page.html out.png"""
import pathlib
import sys

from playwright.sync_api import sync_playwright

src, out = pathlib.Path(sys.argv[1]).resolve(), sys.argv[2]
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=2)
    page.goto(src.as_uri(), wait_until="networkidle")
    page.evaluate("document.fonts.ready")
    page.wait_for_timeout(400)
    over = page.evaluate("document.documentElement.scrollHeight > 1080 || document.documentElement.scrollWidth > 1920")
    page.screenshot(path=out, clip={"x": 0, "y": 0, "width": 1920, "height": 1080})
    print(out, "overflow!" if over else "fits 1920x1080")
    browser.close()
