"""Speaker drafts and atomic saves, without silently overwriting disk edits."""
from copy import deepcopy
from pathlib import Path

from agent_tts import config
from agent_tts.tts.base import PLACEHOLDER_VOICE
from agent_tts.tts.factory import provider_class


class FileChangedError(RuntimeError):
    pass


class Drafts:
    def __init__(self, path):
        self.path = Path(path)
        self.reload()

    def _stamp(self):
        stat = self.path.stat()
        return stat.st_mtime_ns, stat.st_size

    def reload(self):
        self.saved = config.load(self.path)
        self.speakers = deepcopy(self.saved.speakers)
        self.stamp = self._stamp()

    @property
    def dirty(self):
        return {name for name, draft in self.speakers.items() if draft != self.saved.speakers[name]}

    def revert(self, name):
        self.speakers[name] = deepcopy(self.saved.speakers[name])

    def _write(self, candidate):
        if self._stamp() != self.stamp:
            raise FileChangedError("The file changed on disk. Reload before saving.")
        config.save(candidate, self.path)
        self.saved = candidate
        self.stamp = self._stamp()

    def save_speaker(self, name):
        draft = deepcopy(self.speakers[name])
        if not draft.voice_id.strip() or draft.voice_id == PLACEHOLDER_VOICE:
            raise ValueError("Assign a voice before saving this speaker.")
        schema = provider_class(draft.provider).settings_schema
        # Preserve existing unknown provider settings, but validate visible values.
        for key, spec in schema.items():
            draft.settings[key] = spec.coerce(draft.settings.get(key))
        draft.voice_id = draft.voice_id.strip()
        candidate = deepcopy(self.saved)
        candidate.speakers[name] = draft
        self._write(candidate)
        self.speakers[name] = deepcopy(draft)

    def toggle_favorite(self, voice_id):
        candidate = deepcopy(self.saved)
        favorites = candidate.voice_library_favorites
        if voice_id in favorites:
            favorites.remove(voice_id)
        else:
            favorites.append(voice_id)
        self._write(candidate)
