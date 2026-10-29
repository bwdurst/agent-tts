"""Tk-level checks on a withdrawn root: wheel routing, combobox safety, and
the save path. No Dashboard is built, so no hotkeys are registered."""
import tkinter as tk
from tkinter import ttk

import pytest

from agent_tts.gui import scrolling
from agent_tts.gui.speaker_card import SpeakerCard
from agent_tts.gui.widgets import apply_ttk_styles


@pytest.fixture(scope="module")
def _tk_root():
    # One root for the module: repeatedly creating Tk() on Windows is flaky.
    try:
        r = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    r.withdraw()
    apply_ttk_styles(r)
    scrolling.install(r)
    yield r
    r.destroy()


@pytest.fixture
def root(_tk_root):
    yield _tk_root
    for child in _tk_root.winfo_children():
        child.destroy()


def _wheel(root, widget, delta=-120):
    root.update()
    x, y = widget.winfo_rootx() + 5, widget.winfo_rooty() + 5
    widget.event_generate("<MouseWheel>", delta=delta, rootx=x, rooty=y, x=5, y=5)
    root.update()


def test_router_scrolls_text_once(root, monkeypatch):
    t = tk.Text(root, height=3, width=20)
    t.pack()
    t.insert("end", "\n".join(str(i) for i in range(100)))
    scrolling.register(t)
    root.deiconify()
    root.update()
    before = t.yview()[0]
    monkeypatch.setattr(root, "winfo_containing", lambda x, y: t)
    scrolling._on_wheel(root, type("E", (), {"x_root": 0, "y_root": 0, "delta": -120})())
    assert t.yview()[0] > before


def test_class_wheel_handlers_are_removed(root):
    # A "break" binding here would also starve the bind_all router.
    assert root.bind_class("Text", "<MouseWheel>") == ""
    assert root.bind_class("TCombobox", "<MouseWheel>") == ""


def test_combobox_ignores_wheel(root):
    var = tk.StringVar(value="a")
    cb = ttk.Combobox(root, textvariable=var, values=("a", "b", "c"), state="readonly")
    cb.pack()
    root.deiconify()
    _wheel(root, cb)
    assert var.get() == "a"


def test_scrollframe_scrolls_when_content_overflows(root, monkeypatch):
    sf = scrolling.ScrollFrame(root)
    sf.pack()
    sf.canvas.configure(height=50, width=100)
    for i in range(30):
        tk.Label(sf.body, text=str(i)).pack()
    root.deiconify()
    root.update()
    assert sf.canvas.yview()[1] < 1.0
    monkeypatch.setattr(root, "winfo_containing", lambda x, y: sf.body.winfo_children()[0])
    scrolling._on_wheel(root, type("E", (), {"x_root": 0, "y_root": 0, "delta": -120})())
    assert sf.canvas.yview()[0] > 0


def _card(root, provider="xai", settings=None, dirty=None):
    return SpeakerCard(root, "KIRA", provider, "ara", settings or {},
                       on_dirty=(dirty or (lambda n: None)), on_browse=lambda n: None,
                       on_test=lambda n: None, on_save=lambda n: None,
                       on_revert=lambda n: None)


def test_card_load_does_not_mark_dirty(root):
    hits = []
    card = _card(root, dirty=hits.append)
    card.load("elevenlabs", "v1", {"stability": 0.2})
    assert hits == [] and card.provider == "elevenlabs"
    assert card.values()["stability"] == 0.2


def test_card_change_provider_resets_controls_and_marks_dirty(root):
    hits = []
    card = _card(root, dirty=hits.append)
    card.change_provider("cartesia")
    assert hits == ["KIRA"]
    assert set(card.values()) == {"model_id", "speed", "volume", "emotion", "language"}


def test_card_slider_change_marks_dirty(root):
    hits = []
    card = _card(root, dirty=hits.append)
    card._setters["speed"](1.4)
    assert hits and card.values()["speed"] == 1.4


def test_card_values_feed_settings_to_save(root, tmp_path):
    from agent_tts.gui.settings_spec import settings_to_save
    card = _card(root, settings={"speed": 1.2})
    card._setters["speed"](1.45)
    out = settings_to_save(card.controls, card.values(), {"speed": 1.2, "extra": 3})
    assert out == {"speed": 1.45, "extra": 3}


def _library(root, monkeypatch):
    from agent_tts.gui.library_view import LibraryHost, LibraryView
    from agent_tts.tts.base import Voice

    favorites, assignments, previews = [], [], []
    host = LibraryHost(
        get_provider=lambda p: None, speakers=lambda: ["KIRA"],
        speaker_provider=lambda n: "xai", speaker_voice_id=lambda n: "0",
        favorites=lambda: favorites,
        toggle_favorite=lambda v: favorites.append(v.voice_id),
        assign=lambda *args: assignments.append(args),
        preview=lambda *args: previews.append(args), target_changed=lambda n: None,
    )
    monkeypatch.setattr(LibraryView, "_fetch", lambda *a: None)
    library = LibraryView(root, host)
    library.pack(fill="both", expand=True)
    library.refresh_targets()
    library.model.current.finish_load([
        Voice(str(i), f"Voice {i:04}", "test", {}, "") for i in range(1000)])
    library._render()
    return library, favorites, assignments, previews


def test_library_large_catalog_uses_constant_widget_count(root, monkeypatch):
    library, _, _, _ = _library(root, monkeypatch)
    def widget_count(widget):
        return 1 + sum(widget_count(child) for child in widget.winfo_children())
    before = widget_count(library)
    assert len(library.tree.get_children()) == 1000
    library.tree.selection_set("999")
    library.tree.see("999")
    library._selected()
    library.refresh()
    assert library.tree.selection() == ("999",)
    library.search_var.set("Voice 0000")
    library._apply_search()
    assert library.tree.get_children() == ("0",)
    assert widget_count(library) == before
    library.search_var.set("no matching voice")
    library._apply_search()
    assert not library.tree.get_children()
    assert not library.assign_button._enabled


def test_library_actions_follow_selection_and_confirm_target(root, monkeypatch):
    library, favorites, assignments, previews = _library(root, monkeypatch)
    library.tree.selection_set("999")
    library._selected()
    library._favorite_selected()
    library._preview_selected()
    assert favorites == ["999"]
    assert previews[0][1].voice_id == "999"
    library._assign_selected()
    assert not assignments
    library.tree.selection_set("998")
    library._selected()
    assert library._pending is None
    library._assign_selected()
    assert not assignments
    library._assign_selected()
    assert assignments[0][:2] == ("KIRA", "xai")
    assert assignments[0][2].voice_id == "998"
    library._assign_selected()
    library.show_provider("cartesia")
    assert library._pending is None
    assert not library.assign_button._enabled


def test_speaker_switch_retains_unsaved_values(root, monkeypatch, tmp_path):
    from pathlib import Path
    from types import SimpleNamespace
    from agent_tts import config
    from agent_tts.gui.library_view import LibraryView
    from agent_tts.gui.voice_settings import VoiceSettingsPanel

    cfg = config.load(Path(__file__).resolve().parents[1] / "voices.yaml")
    dest = tmp_path / "voices.yaml"
    config.save(cfg, dest)
    app = SimpleNamespace(root=root, cfg=cfg, config_path=dest, log=lambda msg: None)
    monkeypatch.setattr(LibraryView, "_fetch", lambda *a: None)
    panel = VoiceSettingsPanel(root, app)
    panel.pack(fill="both", expand=True)
    names = list(panel.cards)
    first = panel.cards[names[0]]
    first.voice_id.set("edited-voice")
    panel.library.set_target(names[1], notify=True)
    assert not first.winfo_manager()
    assert panel.cards[names[1]].winfo_manager() == "pack"
    panel.library.set_target(names[0], notify=True)
    assert first.voice_id.get() == "edited-voice"
    assert panel.dirty
    panel.save_all_cards()
    assert config.load(dest).speakers[names[0]].voice_id == "edited-voice"
    assert not panel.dirty


def test_resize_surface_coalesces_sizes_and_ignores_moves(root):
    from types import SimpleNamespace
    from agent_tts.gui.resize_surface import ResizeSurface

    surface = ResizeSurface(root)
    def configure(width, height):
        surface._configure_root(SimpleNamespace(widget=root, width=width, height=height))
    configure(1000, 800)
    assert surface._size == (1000, 800)
    configure(1100, 850)
    first_job = surface._job
    configure(1200, 900)
    assert surface._size == (1000, 800)
    assert surface._job != first_job
    job = surface._job
    configure(1200, 900)
    assert surface._job == job
    surface.after_cancel(job)
    surface._apply_size()
    assert surface._size == (1200, 900)
    configure(1200, 900)
    assert surface._job is None
    configure(1300, 900)
    surface.destroy()
    assert surface._job is None


def test_catalog_filter_menus_keep_multiple_selections(root, monkeypatch):
    from agent_tts.tts.base import Voice
    library, _, _, _ = _library(root, monkeypatch)
    library.model.current.finish_load([
        Voice('a', 'A', '', {'language': 'en'}, ''),
        Voice('b', 'B', '', {'language': 'fr'}, ''),
        Voice('c', 'C', '', {'language': 'de'}, ''),
    ])
    library._rebuild_chips()
    library._render()
    button = library.chip_frame.winfo_children()[0]
    menu = button.winfo_children()[0]
    # Alphabetical language options: de, en, fr.
    menu.invoke(1)
    assert set(library.tree.get_children()) == {'a'}
    menu.invoke(2)
    assert set(library.tree.get_children()) == {'a', 'b'}
    library._rebuild_chips()
    assert library.model.current.filters['language'] == {'en', 'fr'}
    assert len(library.chip_frame.winfo_children()) == 1


@pytest.mark.parametrize('orient', ['horizontal', 'vertical'])
@pytest.mark.parametrize('button', [1, 2])
def test_divider_overlay_never_uses_tk_proxy(root, orient, button):
    from agent_tts.gui.panes import GuidePanedWindow
    pane = GuidePanedWindow(root, orient=orient, opaqueresize=False, sashwidth=8,
                           proxybackground='#3b82f6')
    pane.pack(fill='both', expand=True)
    for _ in range(2):
        pane.add(tk.Frame(pane, width=180, height=120), minsize=50)
    root.geometry('600x400')
    root.deiconify()
    root.update()
    proxy_calls = []
    def trace(command, _op):
        if root.tk.splitlist(command)[1] == 'proxy':
            proxy_calls.append(command)
    command = pane.register(trace)
    root.tk.call('trace', 'add', 'execution', str(pane), 'enter', command)
    sx, sy = pane.sash_coord(0)
    x, y = (sx + 2, 20) if orient == 'horizontal' else (20, sy + 2)
    pane.event_generate(f'<ButtonPress-{button}>', x=x, y=y)
    assert pane._overlay is not None
    overlay = pane._overlay
    dx, dy = (40, 0) if orient == 'horizontal' else (0, 40)
    pane.event_generate(f'<B{button}-Motion>', x=x + dx, y=y + dy, state=256 if button == 1 else 512)
    assert pane.sash_coord(0) == (sx, sy)  # no expensive live layout
    pane.event_generate(f'<ButtonRelease-{button}>', x=x + dx, y=y + dy)
    assert pane._overlay is None and pane._drag is None
    assert not overlay.winfo_exists()
    assert pane.sash_coord(0) != (sx, sy)
    assert pane.grab_current() is None
    # Cancelling a second drag must retain the committed divider position.
    before = pane.sash_coord(0)
    x, y = (before[0] + 2, 20) if orient == 'horizontal' else (20, before[1] + 2)
    pane.event_generate(f'<ButtonPress-{button}>', x=x, y=y)
    pane.event_generate(f'<B{button}-Motion>', x=x + dx, y=y + dy, state=256 if button == 1 else 512)
    pane._cancel()
    assert pane.sash_coord(0) == before
    assert pane._overlay is None and pane.grab_current() is None
    assert not proxy_calls
