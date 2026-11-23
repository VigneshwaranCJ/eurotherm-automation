"""Exact record matching and individually verified native channel selection."""

STATUS = "(e, id) => window.angular.element(e).scope().chartSettings.channelStatuses[id]?.selected"


def select_record(groups, record_id, field):
    def value(group):
        for key in field.split('.'):
            group = group.get(key) if isinstance(group, dict) else None
        return group
    matches = [group for group in groups if value(group) == record_id]
    if len(matches) != 1:
        raise ValueError(f'Expected one exact Custom record for {record_id}; found {len(matches)}')
    return matches[0]


def validate_channels(channels, mappings):
    """Require every approved channel within a record that may contain additional channels.

    The approved count (25 combined, or any count when split by channel) is enforced by PipelineConfig.
    """
    names = [c['channelName'] for c in channels]
    expected = [c['name'] for c in mappings]
    if not expected or len(set(expected)) != len(expected):
        raise ValueError(f'Approved channels must be unique and non-empty; got {len(set(expected))} unique of {len(expected)}')
    duplicates = sorted({name for name in names if names.count(name) > 1})
    missing = sorted(set(expected) - set(names))
    if duplicates or missing:
        raise ValueError(f'Channel mapping mismatch: missing={missing}; ambiguous={duplicates}; record channels={len(names)}')
    mapped = {c['channelName']: c for c in channels}
    empty = [name for name in expected if not mapped[name].get('dataPoints')]
    if empty:
        raise ValueError(f'Channels without samples: {empty}')
    return mapped


def select_channels(page, channels, mappings, wanted, log):
    """Set every record channel one at a time with Reviewer's Show/Hide Channel control."""
    mapped = validate_channels(channels, mappings)
    if not set(wanted) <= set(mapped) or len(set(wanted)) != len(wanted):
        raise ValueError('Selected channels must be unique names from the approved mapping')
    wanted = tuple(wanted)
    state = page.locator('#testAuto_chartdisplay_print')
    rows = page.locator('.channel-list:visible [ng-repeat]')
    clicks = 0
    for channel in channels:
        name, on = channel['channelName'], channel['channelName'] in wanted
        row = rows.filter(has=page.locator('.channel-name').get_by_text(name, exact=True))
        if row.count() != 1:
            raise ValueError(f'Channel control is missing or ambiguous: {name}')
        if bool(state.evaluate(STATUS, channel['channelUniqueId'])) != on:
            row.locator('[title="Show/Hide Channel"]').click()
            clicks += 1
        if bool(state.evaluate(STATUS, channel['channelUniqueId'])) != on:
            raise ValueError(f'Reviewer did not accept the requested channel state: {name}')
    # Verify the finished set too, in case a later click changed an earlier channel.
    final = [c['channelName'] for c in channels if bool(state.evaluate(STATUS, c['channelUniqueId']))]
    if set(final) != set(wanted):
        raise ValueError(f'Channel state changed unexpectedly: selected={sorted(final)}')
    deselected = [c['channelName'] for c in channels if c['channelName'] not in wanted]
    log('channelsSelected', dict(available=len(channels), selected=list(wanted), deselected=deselected, clicks=clicks))
    return [mapped[name] for name in wanted]
