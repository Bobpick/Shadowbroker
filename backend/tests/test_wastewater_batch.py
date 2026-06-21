"""Wastewater rotating batch selection tests."""

from services.fetchers.wastewater import select_batch_ids


def _plant_map(ids: list[str], with_data: set[str] | None = None) -> dict[str, dict]:
    loaded = with_data or set()
    return {
        pid: {"id": pid, "pathogens": [{"name": "Rota"}] if pid in loaded else []}
        for pid in ids
    }


def test_select_batch_prioritizes_unfetched_plants():
    ids = ["a", "b", "c", "d", "e"]
    plant_map = _plant_map(ids, with_data={"a", "b"})

    batch, cursor = select_batch_ids(ids, plant_map, cursor=0, batch_size=2)

    assert batch == ["c", "d"]
    assert cursor == 0


def test_select_batch_rotates_after_backlog_cleared():
    ids = ["a", "b", "c", "d"]
    plant_map = _plant_map(ids, with_data=set(ids))

    batch, cursor = select_batch_ids(ids, plant_map, cursor=1, batch_size=2)

    assert batch == ["b", "c"]
    assert cursor == 3


def test_select_batch_wraps_cursor():
    ids = ["a", "b", "c"]
    plant_map = _plant_map(ids, with_data=set(ids))

    batch, cursor = select_batch_ids(ids, plant_map, cursor=2, batch_size=2)

    assert batch == ["c", "a"]
    assert cursor == 1