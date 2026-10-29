from agent_tts import parser
from agent_tts.normalize import normalize


def test_speakers_come_from_the_caller_not_a_fixed_list():
    text = "ORION: First.\nKIRA: Second."
    assert [b.speaker for b in parser.parse(text, ("ORION",))] == ["ORION"]
    assert [b.speaker for b in parser.parse(text, parser.speaker_names({"_default": 0, "ORION": 0, "KIRA": 0}))] == ["ORION", "KIRA"]


def test_named_speakers_code_and_asides_remain_distinct():
    text = "KIRA: Hello.\n```python\nprint(1)\n```\n```aside\nA quiet note.\n```\nTANIS: Goodbye."
    blocks = parser.parse(text)
    assert [(b.speaker, b.text) for b in blocks] == [
        ("KIRA", "Hello."), (parser.CODE, "print(1)"),
        (parser.ASIDE, "A quiet note."), ("TANIS", "Goodbye.")]


def test_unprefixed_and_unknown_names_use_default_parser_behavior():
    blocks = parser.parse("UNKNOWN: Plain prose.")
    assert len(blocks) == 1
    assert blocks[0].speaker == "_default"
    assert blocks[0].text == "UNKNOWN: Plain prose."


def test_normalization_keeps_expression_tags_and_speaker_overrides():
    text = normalize("**Hello** [pause] [world](https://example.com). Kira has 2 ideas.", "KIRA",
                     {"global": {"Kira": "Global"}, "KIRA": {"Kira": "Keera"}})
    assert text == "Hello [pause] world. Keera has two ideas."
