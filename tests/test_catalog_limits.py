"""An incomplete voice catalog must fail loudly instead of passing as complete."""
from unittest.mock import Mock, patch

import pytest

from agent_tts.tts.base import CatalogLimitError
from agent_tts.tts.cartesia_provider import CartesiaProvider
from agent_tts.tts.elevenlabs_provider import ElevenLabsProvider

CASES = [
    (ElevenLabsProvider, "elevenlabs_provider", "next_page_token"),
    (CartesiaProvider, "cartesia_provider", "next_page"),
]


def _response(payload):
    resp = Mock()
    resp.json.return_value = payload
    return resp


@pytest.mark.parametrize("provider_cls, module, cursor_key", CASES)
@pytest.mark.parametrize("repeat_cursor", [True, False])
def test_unbounded_or_cursorless_paging_raises(tmp_path, provider_cls, module, cursor_key, repeat_cursor):
    # has_more with a repeating cursor loops forever; has_more with no cursor cannot advance.
    payload = {"has_more": True, cursor_key: "again"} if repeat_cursor else {"has_more": True}
    instance = provider_cls("fixture-key", "mp3", tmp_path)
    with patch(f"agent_tts.tts.{module}.requests.get", return_value=_response(payload)), pytest.raises(CatalogLimitError):
        instance.list_voices()


@pytest.mark.parametrize("provider_cls, module, cursor_key", CASES)
def test_complete_catalog_still_returns(tmp_path, provider_cls, module, cursor_key):
    instance = provider_cls("fixture-key", "mp3", tmp_path)
    with patch(f"agent_tts.tts.{module}.requests.get", return_value=_response({"has_more": False})):
        assert instance.list_voices() == []
