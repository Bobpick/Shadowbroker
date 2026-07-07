"""Wastewater rotating batch selection tests."""

from datetime import datetime, timedelta, timezone

from services.fetchers.wastewater import (
    _fallback_plants,
    _select_no_data_retry_ids,
    select_batch_ids,
)


def _plant_map(ids: list[str], with_data: set[str] | None = None) -> dict[str, dict]:
    loaded = with_data or set()
    return {
        pid: {"id": pid, "pathogens": [{"name": "Rota"}] if pid in loaded else []}
        for pid in ids
    }


def test_select_batch_prioritizes_unfetched_plants():
    ids = ["a", "b", "c", "d", "e"]
    plant_map = _plant_map(ids, with_data={"a", "b"})

    batch, cursor, unfetched_cursor = select_batch_ids(ids, plant_map, cursor=0, batch_size=2)

    assert batch == ["c", "d"]
    assert cursor == 0
    assert unfetched_cursor == 2


def test_select_batch_rotates_after_backlog_cleared():
    ids = ["a", "b", "c", "d"]
    plant_map = _plant_map(ids, with_data=set(ids))

    batch, cursor, _ = select_batch_ids(ids, plant_map, cursor=1, batch_size=2)

    assert batch == ["b", "c"]
    assert cursor == 3


def test_select_batch_skips_no_data_and_refreshes_loaded_sites():
    ids = ["a", "b", "c", "d", "e"]
    plant_map = _plant_map(ids, with_data={"a", "b"})

    batch, cursor, _ = select_batch_ids(
        ids,
        plant_map,
        cursor=0,
        batch_size=4,
        no_data_ids={"c", "d", "e"},
    )

    assert batch == ["a", "b"]
    assert cursor == 0


def test_fallback_plants_seed_loads_when_network_unavailable():
    plants = _fallback_plants()
    assert len(plants) >= 100
    assert plants[0].get("point", {}).get("coordinates")


def test_select_batch_wraps_cursor():
    ids = ["a", "b", "c"]
    plant_map = _plant_map(ids, with_data=set(ids))

    batch, cursor, _ = select_batch_ids(ids, plant_map, cursor=2, batch_size=2)

    assert batch == ["c", "a"]
    assert cursor == 1


def test_select_batch_prioritizes_stale_loaded_plants():
    ids = ["fresh", "stale", "older"]
    plant_map = {
        "fresh": {
            "id": "fresh",
            "pathogens": [{"name": "Rota"}],
            "sample_age_days": 2,
        },
        "stale": {
            "id": "stale",
            "pathogens": [{"name": "Rota"}],
            "sample_age_days": 18,
        },
        "older": {
            "id": "older",
            "pathogens": [{"name": "Rota"}],
            "sample_age_days": 30,
        },
    }

    batch, _, _ = select_batch_ids(ids, plant_map, cursor=0, batch_size=3)

    assert "older" in batch
    assert batch.index("older") < batch.index("fresh")


def test_select_batch_includes_retry_ids_before_refresh():
    ids = ["a", "b", "c", "d"]
    plant_map = _plant_map(ids, with_data={"a"})

    batch, _, _ = select_batch_ids(
        ids,
        plant_map,
        cursor=0,
        batch_size=3,
        no_data_ids={"c"},
        retry_ids=["c"],
    )

    assert batch[0] == "c"
    assert "b" in batch


def test_select_no_data_retry_ids_rotates_and_respects_cooldown():
    now = datetime.now(timezone.utc)
    state = {
        "no_data_retry_cursor": 0,
        "no_data_since": {
            "fresh": (now - timedelta(hours=1)).isoformat(),
            "cool": (now - timedelta(hours=8)).isoformat(),
        },
    }

    retries, cursor = _select_no_data_retry_ids(state, {"fresh", "cool"}, limit=2)

    assert retries == ["cool"]
    assert cursor == 0