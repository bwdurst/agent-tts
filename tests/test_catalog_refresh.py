"""Changing a provider's key while its voice list is loading must not leave the old result on screen."""
import queue
import threading

import requests

from agent_tts import config
from agent_tts.application.controller import Controller, error_message
from agent_tts.application.drafts import Drafts
from tests.test_application import FakePlayer, pump


def test_in_flight_catalog_from_the_old_key_is_dropped_and_refetched(make_cfg, tmp_path):
    path = tmp_path / "voices.yaml"
    config.save(make_cfg(), path)
    release = threading.Event()
    calls = []

    class Pool:
        def __init__(self, cfg):
            pass

        def get(self, name):
            return self

        def list_voices(self):
            calls.append(1)
            if len(calls) == 1:
                release.wait(2)  # the request that was started with the old key
                return ["old"]
            return ["new"]

    results, events = queue.Queue(), []
    controller = Controller(Drafts(path), results.put, lambda *args: events.append(args), enable_hotkeys=False,
                            player_factory=FakePlayer, pool_factory=Pool)
    try:
        controller.fetch_catalog("xai")
        controller.key_changed("xai")  # first request is still in flight
        assert len(calls) == 1
        release.set()
        pump(controller, results, lambda: controller.catalogs.get("xai") == ["new"])
        assert [e[1][1] for e in events if e[0] == "catalog"] == [["new"]]
        assert len(calls) == 2
    finally:
        controller.close()
        controller._synth_thread.join(1)


def test_rejected_key_message_mentions_that_a_saved_key_overrides_env():
    response = requests.Response()
    response.status_code = 401
    message = error_message(requests.HTTPError(response=response))
    assert "401" in message and "Providers" in message
    response.status_code = 500
    assert "Providers" not in error_message(requests.HTTPError(response=response))
