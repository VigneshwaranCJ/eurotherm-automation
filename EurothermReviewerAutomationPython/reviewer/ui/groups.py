"""Native group filters and cards."""
from ..common.time import utc_time


def all_groups(page, custom=False):
    if page.url.endswith("/groups"):
        page.locator("#testAuto_topMenu_dateSources").click()
        page.wait_for_url("**/#/datasources")
    def filters(response):
        return '/api/groups/' in response.url and response.url.endswith('/filters') and response.status == 200
    # Reviewer reloads whichever tab it remembers: normal, batches or custom.
    with page.expect_response(filters, timeout=90000):
        page.locator("#testAuto_topMenu_groupsAndBatches").click()
    with page.expect_response(filters, timeout=90000):
        page.locator('#loadCustomGroups' if custom else '#loadNormalGroups').click()
    if custom:
        page.locator('#loadCustomGroups.btn-selected').wait_for()
    page.locator("#toggle").click()
    page.wait_for_function("() => window.jQuery('date-picker-filter .date').first().data('DateTimePicker')", timeout=90000)
    def historical_filter(response):
        return (filters(response)
                and utc_time(response.request.post_data_json["start"]) < utc_time("2001-01-01T00:00:00Z"))
    with page.expect_response(historical_filter, timeout=90000) as pending:
        page.locator("date-picker-filter").first.evaluate("""e => {
            const p=window.jQuery(e).find('.date').data('DateTimePicker');
            p.show(); p.date(window.moment('2000-01-01')); p.hide();
        }""")
    data = pending.value.json()
    page.get_by_text("Close", exact=True).click()
    if data["totalCount"] > len(data["groups"]):
        raise RuntimeError("Group results are paginated; refine group selection before proceeding")
    return data["groups"]


CARD_INDEXES = """(elements, groupId) => elements.flatMap((element, index) =>
    window.angular.element(element).scope()?.card?.groupId === groupId ? [index] : [])"""


def group_card(page, group):
    """Locate one card by Reviewer's own group ID; display names can overlap (EUT-01, SLS733(EUT-01))."""
    group_id = group["groupId"]
    cards = page.locator(".box-body")
    page.wait_for_function(
        """groupId => [...document.querySelectorAll('.box-body')]
            .some(e => window.angular.element(e).scope()?.card?.groupId === groupId)""",
        arg=group_id, timeout=30000)
    matches = cards.evaluate_all(CARD_INDEXES, group_id)
    if len(matches) != 1:
        raise RuntimeError(f"Expected one card for {group['groupName']!r} ({group_id}); found {len(matches)}")
    return cards.nth(matches[0])
