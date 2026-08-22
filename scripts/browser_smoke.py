import os
from pathlib import Path

from playwright.sync_api import sync_playwright

errors: list[str] = []
base_url = os.environ.get("CLIPAUTO_TEST_URL", "http://127.0.0.1:8765")
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
    page.on(
        "console", lambda message: errors.append(message.text) if message.type == "error" else None
    )
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(base_url)
    page.wait_for_load_state("networkidle")
    page.locator("#batch-form").wait_for()
    page.locator("#workspace:not([hidden])").wait_for()
    page.get_by_role("link", name="Download ZIP").wait_for()
    assert page.locator("video").count() == 0
    first_job = page.locator(".job").first
    first_job.get_by_role("button", name="Show 1 clip").click()
    first_job.get_by_role("button", name="Hide 1 clip").wait_for()
    assert first_job.locator("video").count() == 1
    assert page.locator("video").count() == 1
    page.get_by_role("button", name="Export MP4s").click()
    page.locator("#export-status").filter(has_text="Saved 2 MP4s to").wait_for()
    assert page.locator("body").evaluate("el => el.scrollWidth <= window.innerWidth")
    intake = page.locator(".intake").bounding_box()
    assert intake and intake["y"] < 220 and intake["height"] < 360, intake
    page.screenshot(path="/tmp/clipauto-desktop.png", full_page=True)
    assert not errors, f"Browser console errors before validation check: {errors}"

    removed_job_id = first_job.get_attribute("data-job-id")
    removed_job = page.locator(f'[data-job-id="{removed_job_id}"]')
    page.once("dialog", lambda dialog: dialog.accept())
    removed_job.get_by_role("button", name="Delete video").click()
    removed_job.wait_for(state="detached")
    assert page.locator(".job").count() == 1
    assert page.locator("#workspace:not([hidden])").count() == 1

    page.locator("#urls").fill("https://example.com/not-youtube")
    page.get_by_role("button", name="Create clips").click()
    page.locator("#form-error:not([hidden])").wait_for()
    assert "not valid YouTube" in page.locator("#form-error").inner_text()
    errors.clear()  # Chromium logs the expected HTTP 422 as a failed resource.

    page.set_viewport_size({"width": 390, "height": 844})
    page.reload()
    page.wait_for_load_state("networkidle")
    page.locator("#workspace:not([hidden])").wait_for()
    assert page.locator("body").evaluate("el => el.scrollWidth <= window.innerWidth")
    mobile_intake = page.locator(".intake").bounding_box()
    assert mobile_intake and mobile_intake["y"] < 260, mobile_intake
    page.screenshot(path="/tmp/clipauto-mobile.png", full_page=True)

    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Clear history").click()
    page.locator("#workspace").wait_for(state="hidden")
    assert page.locator(".job").count() == 0
    browser.close()

if errors:
    raise AssertionError(f"Browser console errors: {errors}")
print(
    "browser-smoke: lazy preview, export, single-video deletion, desktop, mobile, and "
    "clear-history states passed without console errors"
)
print(Path("/tmp/clipauto-desktop.png"), Path("/tmp/clipauto-mobile.png"))
