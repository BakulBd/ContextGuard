import pytest

from contextguard.zones import Zone, ZoneManager

OUTER = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
INNER = [(0.4, 0.4), (0.6, 0.4), (0.6, 0.6), (0.4, 0.6)]


def test_zone_rejects_bad_kind():
    with pytest.raises(ValueError):
        Zone(name="x", kind="dangerous", polygon=OUTER)


def test_zone_rejects_too_few_points():
    with pytest.raises(ValueError):
        Zone(name="x", kind="normal", polygon=[(0, 0), (1, 1)])


def test_smallest_zone_wins_when_nested():
    zm = ZoneManager(zones=[Zone("lab", "normal", OUTER), Zone("server-closet", "restricted", INNER)])
    hit = zm.zone_for_point((0.5, 0.5))
    assert hit.name == "server-closet"

    outside_inner = zm.zone_for_point((0.1, 0.1))
    assert outside_inner.name == "lab"

    outside_both = zm.zone_for_point((2.0, 2.0))
    assert outside_both is None


def test_add_replaces_same_name():
    zm = ZoneManager()
    zm.add(Zone("door", "normal", OUTER))
    zm.add(Zone("door", "restricted", INNER))
    assert len(zm.zones) == 1
    assert zm.get("door").kind == "restricted"


def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "zones.json"
    zm = ZoneManager(zones=[Zone("lab", "normal", OUTER), Zone("server-closet", "restricted", INNER)], path=path)
    zm.save()

    loaded = ZoneManager.load(path)
    assert {z.name for z in loaded.zones} == {"lab", "server-closet"}
    assert loaded.get("server-closet").kind == "restricted"


def test_load_missing_file_returns_empty_manager(tmp_path):
    zm = ZoneManager.load(tmp_path / "nope.json")
    assert zm.zones == []


def test_restricted_zones_filter():
    zm = ZoneManager(zones=[Zone("lab", "normal", OUTER), Zone("server-closet", "restricted", INNER)])
    assert [z.name for z in zm.restricted_zones()] == ["server-closet"]
