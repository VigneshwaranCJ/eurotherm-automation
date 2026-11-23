"""Read-only native batch inspection."""
import re
from .groups import all_groups, group_card


def inspect_batches(page, group, metadata, settings, log):
    action = group_card(page, group).locator("xpath=..").locator('[title="Go to batches"]')
    with page.expect_response(lambda r: "/api/groups/batches/filters" in r.url and r.status == 200, timeout=90000) as pending:
        action.click()
    data = pending.value.json()
    log("batches", dict(count=data["totalCount"], batches=data.get("batches", []),
                        fileBatchRecords=[r for r in metadata["Records"] if re.search(r"Batch(Start|Header|Stop)Record", r["kind"])]))
    if settings.batch:
        raise RuntimeError("Batch-specific reporting requires verified batch matching; this UHH test is a continuous group recording")
    all_groups(page)
