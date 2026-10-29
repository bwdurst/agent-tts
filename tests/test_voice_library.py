from agent_tts import voice_library
from agent_tts.tts.base import Voice


def _v(i, name, gender="male"):
    return Voice(i, name, "", {"gender": gender}, "")


def test_fetch_delegates_to_provider():
    class P:
        def list_voices(self):
            return [_v("1", "One")]

    assert voice_library.fetch_voices(P())[0].voice_id == "1"


def test_filter_search_chips_and_favorites_first():
    voices = [_v("1", "Alpha"), _v("2", "Beta", "female"), _v("3", "Alfred")]
    out = voice_library.filter_voices(voices, search="al")
    assert [v.voice_id for v in out] == ["1", "3"]
    out = voice_library.filter_voices(voices, active_filters={"gender": {"female"}})
    assert [v.voice_id for v in out] == ["2"]
    out = voice_library.filter_voices(voices, favorites=["3"])
    assert out[0].voice_id == "3"
    assert voice_library.label_values(voices, "gender") == ["female", "male"]
