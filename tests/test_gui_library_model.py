import requests

from agent_tts.gui import library_model as lm
from agent_tts.gui.scrolling import wheel_steps
from agent_tts.tts.base import Voice


def v(vid, name, **labels):
    return Voice(vid, name, "", labels, "")


def test_tabs_are_the_three_providers_in_order():
    assert lm.tab_order() == ["xai", "elevenlabs", "cartesia"]
    assert [lm.tab_label(p) for p in lm.tab_order()] == ["xAI", "ElevenLabs", "Cartesia"]


def test_each_tab_keeps_its_own_state():
    model = lm.LibraryModel()
    model.select("elevenlabs").finish_load([v("a", "Ana", gender="female")])
    model.select("cartesia").fail_load("nope")
    assert model.tabs["elevenlabs"].loaded and not model.tabs["xai"].loaded
    assert model.tabs["cartesia"].error == "nope"
    assert model.tabs["xai"].needs_fetch and not model.tabs["elevenlabs"].needs_fetch


def test_filters_and_search_are_per_tab_and_favorites_float():
    tab = lm.TabState("xai")
    tab.finish_load([v("1", "Ara", gender="female"), v("2", "Rex", gender="male"),
                     v("3", "Eve", gender="female")])
    tab.toggle_filter("gender", "female", True)
    assert [x.name for x in tab.visible("", [])] == ["Ara", "Eve"]
    assert [x.name for x in tab.visible("", ["3"])] == ["Eve", "Ara"]
    tab.toggle_filter("gender", "female", False)
    assert len(tab.visible("rex", [])) == 1


def test_categories_need_two_values():
    tab = lm.TabState("xai")
    tab.finish_load([v("1", "A", gender="f", language="en"), v("2", "B", gender="m", language="en")])
    assert list(tab.categories()) == ["gender"]


def test_describe_error_missing_key_and_rejected_key_and_network():
    assert "not set up" in lm.describe_error("cartesia", RuntimeError("CARTESIA_API_KEY not set (check .env)"))
    assert "CARTESIA_API_KEY" in lm.describe_error("cartesia", RuntimeError("CARTESIA_API_KEY not set"))
    resp = requests.Response()
    resp.status_code = 401
    msg = lm.describe_error("xai", requests.HTTPError("401", response=resp))
    assert "rejected" in msg and "XAI_API_KEY" in msg
    assert "Couldn't reach ElevenLabs" in lm.describe_error("elevenlabs", ConnectionError("down"))


def test_wheel_steps_direction_and_minimum():
    assert wheel_steps(120) < 0 < wheel_steps(-120)
    assert wheel_steps(10) == -1 and wheel_steps(-10) == 1
    assert wheel_steps(0) == 0
    assert abs(wheel_steps(240)) == 2 * abs(wheel_steps(120))
