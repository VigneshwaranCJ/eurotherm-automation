"""Read-only native notification evidence."""
from urllib.parse import urlparse


def inspect_notifications(page, settings, log, run_id):
    responses = []
    def listener(response):
        if "notification" in response.url.lower():
            responses.append(dict(path=urlparse(response.url).path, status=response.status))
    page.on("response", listener)
    try:
        page.locator("#testAuto_topMenu_notifications").click()
        page.wait_for_url("**/#/notifications")
        page.get_by_text("Number of notifications", exact=True).wait_for()
        page.wait_for_timeout(1000)
        log("notifications", dict(text=page.locator("body").inner_text(), responses=responses, acknowledged=False))
        page.screenshot(path=str(settings.screenshots / f"notifications-{run_id}.png"), full_page=True)
    finally:
        page.remove_listener("response", listener)
