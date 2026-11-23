from contextlib import contextmanager
from urllib.parse import urlparse

from playwright.sync_api import Error, sync_playwright


@contextmanager
def open_reviewer(settings):
    with sync_playwright() as playwright:
        options = {"headless": settings.headless}
        if settings.channel:
            options["channel"] = settings.channel
        browser = playwright.chromium.launch(**options)
        try:
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()
            try:
                page.goto(settings.url, timeout=90000)
            except Error as error:
                if not settings.tls_exception or "CERT" not in str(error).upper():
                    raise
                context.close()
                context = browser.new_context(ignore_https_errors=True, accept_downloads=True)
                context.route(
                    "**/*",
                    lambda route: route.continue_()
                    if urlparse(route.request.url).hostname == "localhost"
                    else route.abort(),
                )
                page = context.new_page()
                page.goto(settings.url, timeout=90000)
            page.set_default_timeout(30000)
            page.wait_for_function(
                "() => window.angular?.element(document.body).scope()?.$root.globalSettings?.dateFormat",
                timeout=90000,
            )
            yield page
        finally:
            browser.close()
