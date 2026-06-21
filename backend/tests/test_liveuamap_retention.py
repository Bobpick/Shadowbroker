"""LiveUAMap marker retention window."""

from datetime import datetime, timezone

from services.liveuamap_retention import prune_liveuamap_incidents

_FIXED_NOW = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)


def test_prune_liveuamap_incidents_drops_markers_older_than_max_age():
    recent_ts = int(datetime(2026, 6, 15, 10, 0, tzinfo=timezone.utc).timestamp())
    old_ts = int(datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc).timestamp())
    incidents = [
        {"id": "new", "timestamp": recent_ts, "title": "Fresh strike"},
        {"id": "old", "timestamp": old_ts, "title": "Winter event"},
        {"id": "unknown", "title": "No timestamp"},
    ]
    pruned = prune_liveuamap_incidents(incidents, max_age_days=7, now=_FIXED_NOW)
    assert [row["id"] for row in pruned] == ["new"]