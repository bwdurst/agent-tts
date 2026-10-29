"""Voice Settings: speaker cards on the left, the provider-tabbed Voice
Library on the right, plus save/revert/test behavior for the cards."""
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from agent_tts import config as cfgmod
from agent_tts import voice_library
from agent_tts.gui.library_model import tab_label
from agent_tts.gui.library_view import LibraryHost, LibraryView
from agent_tts.gui.scrolling import ScrollFrame
from agent_tts.gui.settings_spec import settings_to_save
from agent_tts.gui.speaker_card import SpeakerCard
from agent_tts.gui.panes import GuidePanedWindow
from agent_tts.gui.theme import (
    ACCENT, BG_CARD, BORDER, DANGER, FG, FG_DIM, FONT_SECTION, FONT_UI_SMALL,
)
from agent_tts.gui.widgets import ModernButton
from agent_tts.normalize import normalize
from agent_tts.tts.base import Provider, Voice

# Deliberately voice-acting focused: opener + question + terse attack + three
# contrasting emotional quotes + confident close. Gives every voice a chance
# to show range in ~20 seconds, and is not tied to any character.
TEST_LINE = (
    "Testing — one, two, three. Is this thing on? Good. "
    "Here's the real test: 'ship it' should sound decisive, "
    "'that's elegant' should sound like I mean it, and "
    "'wait, that's wrong' should feel urgent. "
    "Same voice, three moods. Let's see what you can do."
)


class VoiceSettingsPanel(tk.Frame):
    def __init__(self, parent, app):
        """`app` supplies: root, cfg, config_path, pq, get_pool(), log(msg)."""
        super().__init__(parent, bg=BG_CARD, bd=0, highlightthickness=1,
                         highlightbackground=BORDER)
        self.app = app
        self._dirty: set[str] = set()
        self.cards: dict[str, SpeakerCard] = {}
        self._selected_name: str | None = None

        header = tk.Frame(self, bg=BG_CARD)
        header.pack(fill="x", padx=16, pady=(12, 4))
        tk.Label(header, text="Voice Settings", bg=BG_CARD, fg=FG,
                 font=FONT_SECTION).pack(side="left")
        self.dirty_label = tk.Label(header, text="", bg=BG_CARD, fg=ACCENT,
                                    font=FONT_UI_SMALL)
        self.dirty_label.pack(side="left", padx=(10, 0))
        self.save_all = ModernButton(header, "Save all", command=self.save_all_cards,
                                     style="primary", padx=14, pady=6, font=FONT_UI_SMALL)
        self.save_all.pack(side="right")

        # Both panes stretch, so the window's extra width is shared instead of
        # one column sitting beside empty space.
        split = GuidePanedWindow(self, orient="horizontal", bg=BG_CARD, bd=0,
                               sashwidth=8, sashrelief="flat", sashpad=0,
                               opaqueresize=False, proxybackground=ACCENT,
                               borderwidth=0, showhandle=False,
                               sashcursor="sb_h_double_arrow")
        split.pack(fill="both", expand=True, padx=12, pady=(4, 12))

        editor = tk.Frame(split, bg=BG_CARD)
        split.add(editor, stretch="always", minsize=440, width=560)
        picker = tk.Frame(editor, bg=BG_CARD)
        picker.pack(fill="x", pady=(0, 8))
        tk.Label(picker, text="Speaker", bg=BG_CARD, fg=FG,
                 font=FONT_SECTION).pack(side="left")
        self.speaker_var = tk.StringVar()
        self.speaker_picker = ttk.Combobox(
            picker, textvariable=self.speaker_var, values=list(self.app.cfg.speakers),
            state="readonly", style="Dark.TCombobox", width=18)
        self.speaker_picker.pack(side="right")
        self.speaker_picker.bind("<<ComboboxSelected>>",
                                 lambda _e: self._browse(self.speaker_var.get()))
        self.cards_scroll = ScrollFrame(editor)
        self.cards_scroll.pack(fill="both", expand=True)

        lib_wrap = tk.Frame(split, bg=BG_CARD)
        split.add(lib_wrap, stretch="always", minsize=350, width=560)
        host = LibraryHost(
            get_provider=lambda p: self.app.get_pool().get(p),
            speakers=lambda: list(self.cards),
            speaker_provider=lambda n: self.cards[n].provider,
            speaker_voice_id=lambda n: self.cards[n].voice_id.get().strip(),
            favorites=lambda: self.app.cfg.voice_library_favorites,
            toggle_favorite=self._toggle_favorite,
            assign=self._assign,
            preview=self._preview,
            target_changed=self._select_card,
        )
        self.library = LibraryView(lib_wrap, host)
        self.library.pack(fill="both", expand=True, padx=(8, 0))

        for name, sc in self.app.cfg.speakers.items():
            card = SpeakerCard(
                self.cards_scroll.body, name, sc.provider, sc.voice_id, sc.settings,
                on_dirty=self._mark_dirty, on_browse=self._browse,
                on_test=self.test_speaker, on_save=self.save_card,
                on_revert=self.revert_card,
            )
            self.cards[name] = card
        self.library.refresh_targets()
        self._select_card(self.library.target)

    # ---- dirty state -----------------------------------------------------
    @property
    def dirty(self) -> bool:
        return bool(self._dirty)

    def _mark_dirty(self, name: str) -> None:
        self._dirty.add(name)
        self.dirty_label.configure(text="• unsaved changes")

    def _clear_dirty(self, name: str | None = None) -> None:
        self._dirty.clear() if name is None else self._dirty.discard(name)
        if not self._dirty:
            self.dirty_label.configure(text="")

    # ---- card selection / browse ---------------------------------------
    def _select_card(self, name: str | None) -> None:
        if name == self._selected_name or name not in self.cards:
            return
        if self._selected_name is not None:
            self.cards[self._selected_name].pack_forget()
        self._selected_name = name
        self.speaker_var.set(name)
        self.cards[name].pack(fill="x", pady=(0, 8), padx=(0, 4))
        self.cards[name].set_selected(True)
        self.cards_scroll.scroll_to_top()

    def _browse(self, name: str) -> None:
        self.library.set_target(name)
        self._select_card(name)
        self.library.focus_search()

    # ---- save / revert ---------------------------------------------------
    def _apply_card(self, name: str, fresh_cfg) -> None:
        card = self.cards[name]
        sc = fresh_cfg.speakers[name]
        existing = sc.settings if sc.provider == card.provider else {}
        sc.settings = settings_to_save(card.controls, card.values(), existing)
        sc.provider = card.provider
        vid = card.voice_id.get().strip()
        if vid:
            sc.voice_id = vid

    def _sync_memory(self, name: str, fresh_cfg) -> None:
        mine = self.app.cfg.speakers[name]
        sc = fresh_cfg.speakers[name]
        mine.provider, mine.voice_id, mine.settings = sc.provider, sc.voice_id, dict(sc.settings)

    def save_all_cards(self) -> None:
        # Re-read the file first so keys that exist on disk but not in the UI
        # (and other edits) are preserved.
        # Only cards the user changed are applied: an untouched card may hold
        # stale values if voices.yaml was edited while the window was open.
        fresh = cfgmod.load(self.app.config_path)
        names = [n for n in self.cards if n in self._dirty and n in fresh.speakers]
        for name in names:
            self._apply_card(name, fresh)
        cfgmod.save(fresh, self.app.config_path)
        for name in names:
            self._sync_memory(name, fresh)
        self._clear_dirty()
        self.app.log("Settings saved to voices.yaml")

    def save_card(self, name: str) -> None:
        fresh = cfgmod.load(self.app.config_path)
        if name not in fresh.speakers:
            self.app.log(f"'{name}' not found in voices.yaml")
            return
        self._apply_card(name, fresh)
        cfgmod.save(fresh, self.app.config_path)
        self._sync_memory(name, fresh)
        self._clear_dirty(name)
        self.app.log(f"Saved {name}")

    def revert_card(self, name: str) -> None:
        fresh = cfgmod.load(self.app.config_path)
        sc = fresh.speakers.get(name)
        if not sc:
            self.app.log(f"'{name}' not found in voices.yaml")
            return
        self.cards[name].load(sc.provider, sc.voice_id, sc.settings)
        self._sync_memory(name, fresh)
        self._clear_dirty(name)
        self.library.refresh()
        self.app.log(f"Reverted {name} to saved values")

    # ---- test ------------------------------------------------------------
    def test_speaker(self, name: str) -> None:
        """Play the test line with the card's *current* values, saved or not."""
        card = self.cards[name]
        saved = self.app.cfg.speakers[name]
        voice_id = card.voice_id.get().strip() or (
            saved.voice_id if saved.provider == card.provider else "")
        try:
            provider = self.app.get_pool().get(card.provider)
        except (RuntimeError, ValueError) as e:
            messagebox.showerror("Provider Error", str(e))
            return
        self.app.transcript.append_block(name, TEST_LINE)
        threading.Thread(
            target=self._do_test,
            args=(name, provider, voice_id, card.values()), daemon=True,
        ).start()

    def _do_test(self, name: str, provider: Provider, voice_id: str, settings: dict) -> None:
        try:
            text = normalize(TEST_LINE, name, self.app.cfg.pronunciations)
            audio = provider.synth(text, voice_id, settings)
        except Exception as e:
            self.app.root.after(0, lambda e=e: self.app.log(f"test failed: {e}"))
            return
        self.app.play(audio, name)

    # ---- library host callbacks ------------------------------------------
    def _assign(self, target: str, provider: str, voice: Voice) -> None:
        card = self.cards[target]
        card.change_provider(provider)
        card.voice_id.set(voice.voice_id)  # trace marks the card dirty

    def _toggle_favorite(self, voice: Voice) -> None:
        """Favorites are a navigation preference, not a tuning change, so they
        persist immediately and stay out of the unsaved-changes indicator."""
        favorites = list(self.app.cfg.voice_library_favorites)
        if voice.voice_id in favorites:
            favorites.remove(voice.voice_id)
        else:
            favorites.append(voice.voice_id)
        fresh = cfgmod.load(self.app.config_path)
        fresh.voice_library_favorites = favorites
        cfgmod.save(fresh, self.app.config_path)
        self.app.cfg.voice_library_favorites = favorites
        self.library.refresh()

    def _preview(self, provider: str, voice: Voice, footer: Callable[[str, str], None]) -> None:
        if not voice.preview_url:
            footer(f"{voice.name} has no preview audio from {tab_label(provider)}. "
                   "Use Test on a card after assigning.", FG_DIM)
            return
        footer(f"Loading {voice.name}…", FG_DIM)
        threading.Thread(target=self._do_preview, args=(provider, voice, footer),
                         daemon=True).start()

    def _do_preview(self, provider: str, voice: Voice, footer) -> None:
        after = self.app.root.after
        dest = self.app.cfg.cache_dir / "voice_previews" / f"{provider}_{voice.voice_id}.mp3"
        try:
            path = voice_library.download_preview(voice.preview_url, dest)
        except Exception as e:
            after(0, lambda err=e: footer(f"Preview failed: {err}", DANGER))
            return
        after(0, lambda: footer("", FG_DIM))
        try:
            self.app.play(path, voice.name)
        except Exception as e:
            after(0, lambda err=e: footer(f"Playback failed: {err}", DANGER))

