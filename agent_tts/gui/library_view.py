"""Voice Library with one tab per provider (xAI, ElevenLabs, Cartesia)."""
import threading
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, ttk
from typing import Callable

from agent_tts import voice_library
from agent_tts.gui.library_model import LibraryModel, describe_error, tab_label, tab_order
from agent_tts.gui import scrolling
from agent_tts.gui.theme import (
    ACCENT, BG_CARD, BG_ELEV, BORDER, DANGER, FG, FG_DIM,
    FONT_SECTION, FONT_UI, FONT_UI_SMALL, OK,
)
from agent_tts.gui.widgets import ModernButton, SearchEntry, TabStrip
from agent_tts.tts.base import Provider, Voice

CONFIRM_MS = 4000


@dataclass
class LibraryHost:
    """What the library needs from the app, kept narrow so it can be tested
    and so the view never reaches into app state."""
    get_provider: Callable[[str], Provider]   # raises RuntimeError/ValueError
    speakers: Callable[[], list[str]]
    speaker_provider: Callable[[str], str]
    speaker_voice_id: Callable[[str], str]
    favorites: Callable[[], list[str]]
    toggle_favorite: Callable[[Voice], None]
    assign: Callable[[str, str, Voice], None]  # speaker, provider, voice
    preview: Callable[[str, Voice, Callable[[str, str], None]], None]
    target_changed: Callable[[str], None]


class LibraryView(tk.Frame):
    def __init__(self, parent, host: LibraryHost):
        super().__init__(parent, bg=BG_CARD)
        self.host = host
        self.model = LibraryModel()
        self.target: str | None = None
        self._pending: tuple[str, str, str] | None = None  # provider, voice_id, target
        self._pending_job: str | None = None
        self._search_job: str | None = None
        self._voices: dict[str, Voice] = {}
        self._selection: str | None = None

        header = tk.Frame(self, bg=BG_CARD)
        header.pack(fill="x", pady=(0, 6))
        tk.Label(header, text="Voice Library", bg=BG_CARD, fg=FG,
                 font=FONT_SECTION).pack(side="left")
        self.target_var = tk.StringVar()
        self.target_box = ttk.Combobox(header, textvariable=self.target_var, width=10,
                                       state="readonly", style="Dark.TCombobox", font=FONT_UI)
        self.target_box.pack(side="right")
        self.target_box.bind("<<ComboboxSelected>>",
                             lambda _e: self.set_target(self.target_var.get(), notify=True))
        tk.Label(header, text="Assign to", bg=BG_CARD, fg=FG_DIM,
                 font=FONT_UI_SMALL).pack(side="right", padx=(0, 8))

        self.tabs = TabStrip(self, [(p, tab_label(p)) for p in tab_order()],
                             on_select=self._on_tab)
        self.tabs.pack(fill="x")
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", pady=(0, 8))

        self.search_var = tk.StringVar()
        self.search = SearchEntry(self, hint="Search voices by name", textvariable=self.search_var)
        self.search.pack(fill="x", ipady=6, ipadx=8, pady=(0, 8))
        self.search_var.trace_add("write", self._on_search)

        self.chip_frame = tk.Frame(self, bg=BG_CARD)
        self.chip_frame.pack(fill="x")

        self.footer = tk.Label(self, text="", bg=BG_CARD, fg=FG_DIM, font=FONT_UI_SMALL,
                               anchor="w", justify="left")
        self.footer.pack(side="bottom", fill="x", pady=(6, 0))
        self.footer.bind("<Configure>", self._on_text_width)

        actions = tk.Frame(self, bg=BG_CARD)
        actions.pack(side="bottom", fill="x", pady=(6, 0))
        self.favorite_button = ModernButton(actions, "Favorite", command=self._favorite_selected,
                                           padx=10, pady=6, font=FONT_UI_SMALL)
        self.favorite_button.pack(side="left")
        self.preview_button = ModernButton(actions, "Preview", command=self._preview_selected,
                                          padx=10, pady=6, font=FONT_UI_SMALL)
        self.preview_button.pack(side="left", padx=6)
        self.details_button = ModernButton(actions, "Details", command=self._show_details,
                                          padx=8, pady=6, font=FONT_UI_SMALL)
        self.details_button.pack(side="left")
        self.assign_button = ModernButton(actions, "Assign", command=self._assign_selected,
                                         padx=10, pady=6, font=FONT_UI_SMALL)
        self.assign_button.pack(side="right")
        table = tk.Frame(self, bg=BG_CARD)
        table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table, columns=("name", "description", "status"), show="headings",
                                 selectmode="browse", style="Voices.Treeview", height=5)
        self.tree.heading("name", text="Voice")
        self.tree.heading("description", text="Description")
        self.tree.heading("status", text="Status")
        self.tree.column("name", width=140, minwidth=100, stretch=True)
        self.tree.column("description", width=200, minwidth=80, stretch=True)
        self.tree.column("status", width=75, minwidth=65, stretch=False)
        bar = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        bar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.pack(fill="both", expand=True)
        scrolling.register(self.tree)
        self.tree.bind("<<TreeviewSelect>>", self._selected)
        self.tree.bind("<Return>", lambda _e: self._assign_selected())
        self.tree.bind("<Double-1>", lambda _e: self._show_details())
        self.retry_button = ModernButton(self, "Try again", command=self._retry,
                                        padx=10, pady=6, font=FONT_UI_SMALL)
        self._sync_actions()

    def _on_text_width(self, event) -> None:
        width = max(100, event.width)
        if int(event.widget.cget("wraplength")) != width:
            event.widget.configure(wraplength=width)

    def _selected_voice(self) -> Voice | None:
        selected = self.tree.selection()
        return self._voices.get(selected[0]) if selected else None

    def _selected(self, _event=None) -> None:
        voice = self._selected_voice()
        selection = voice.voice_id if voice else None
        if selection != self._selection:
            self._cancel_confirm()
            self._selection = selection
        self._sync_actions()

    def _sync_actions(self) -> None:
        voice = self._selected_voice()
        for button in (self.favorite_button, self.preview_button, self.assign_button,
                       self.details_button):
            button.set_enabled(voice is not None)
        self.favorite_button.set_text(
            "Unfavorite" if voice and voice.voice_id in self.host.favorites() else "Favorite")
        if self._pending is None:
            in_use = (voice and self.target
                      and self.host.speaker_provider(self.target) == self.model.selected
                      and self.host.speaker_voice_id(self.target) == voice.voice_id)
            self.assign_button.set_text("In use" if in_use else "Assign")

    def _show_details(self) -> None:
        voice = self._selected_voice()
        if voice:
            messagebox.showinfo(voice.name, voice.description or "No description available.",
                                parent=self)

    def _favorite_selected(self) -> None:
        voice = self._selected_voice()
        if voice:
            self.host.toggle_favorite(voice)

    def _preview_selected(self) -> None:
        voice = self._selected_voice()
        if voice:
            self.host.preview(self.model.selected, voice, self._set_footer)

    def _assign_selected(self) -> None:
        voice = self._selected_voice()
        if voice:
            self._assign_clicked(self.model.selected, voice)

    # ---- public ------------------------------------------------------------
    def refresh_targets(self) -> None:
        names = self.host.speakers()
        self.target_box.configure(values=names)
        if self.target is None and names:
            self.set_target(names[0])

    def set_target(self, name: str, *, notify: bool = False) -> None:
        self.target = name
        self.target_var.set(name)
        self._cancel_confirm()
        if notify:
            self.host.target_changed(name)
        self.show_provider(self.host.speaker_provider(name))

    def show_provider(self, provider: str) -> None:
        if provider not in self.model.tabs:
            return
        if self.tabs.selected == provider:
            self._render()  # same tab: the target or its voice changed
        else:
            self.tabs.select(provider)  # fires _on_tab

    def focus_search(self) -> None:
        self.search.focus_set()
        self.search.select_range(0, "end")

    def refresh(self) -> None:
        # Starring or assigning changes a row, not the result set: keep the place.
        self._render(reset_scroll=False)

    # ---- tabs and fetching -------------------------------------------------
    def _on_tab(self, provider: str) -> None:
        self._cancel_confirm()
        self.model.select(provider)
        self._rebuild_chips()
        self._render()
        if self.model.current.needs_fetch:
            self._fetch(provider)

    def _fetch(self, provider: str) -> None:
        tab = self.model.tabs[provider]
        try:
            api = self.host.get_provider(provider)
        except (RuntimeError, ValueError) as e:
            tab.fail_load(describe_error(provider, e))
            self._render()
            return
        tab.start_load()
        self._render()

        def worker():
            try:
                voices = voice_library.fetch_voices(api)
            except Exception as e:  # network, auth, schema: all become tab text
                self.after(0, lambda e=e: self._fetched(provider, None, e))
                return
            self.after(0, lambda: self._fetched(provider, voices, None))

        threading.Thread(target=worker, daemon=True).start()

    def _fetched(self, provider: str, voices: list[Voice] | None, err: Exception | None) -> None:
        tab = self.model.tabs[provider]
        if err is not None:
            tab.fail_load(describe_error(provider, err))
        else:
            tab.finish_load(voices or [])
        if provider == self.model.selected:
            self._rebuild_chips()
            self._render()

    # ---- search and chips --------------------------------------------------
    def _on_search(self, *_a) -> None:
        if self._search_job is not None:
            self.after_cancel(self._search_job)
        self._search_job = self.after(150, self._apply_search)

    def _apply_search(self) -> None:
        self._search_job = None
        self._render()

    def _rebuild_chips(self) -> None:
        # Catalogs may contain dozens of languages/accents. Native menu items
        # retain multi-select filters without creating a widget per option.
        for child in self.chip_frame.winfo_children():
            child.destroy()
        self._filter_vars = []
        tab = self.model.current
        for category, values in tab.categories().items():
            active = tab.filters.get(category, set())
            label = f"{category.title()}: {len(active) if active else 'All'}"
            button = tk.Menubutton(self.chip_frame, text=label, bg=BG_ELEV, fg=FG,
                                   activebackground=BG_CARD, activeforeground=FG,
                                   font=FONT_UI_SMALL, padx=8, pady=5, takefocus=True,
                                   relief="flat", direction="below")
            button.pack(side="left", padx=(0, 6), pady=(0, 6))
            menu = tk.Menu(button, tearoff=False, bg=BG_ELEV, fg=FG,
                           activebackground=ACCENT, activeforeground=FG)
            button.configure(menu=menu)
            for value in values:
                var = tk.BooleanVar(value=value in active)
                self._filter_vars.append(var)
                def toggle(c=category, v=value, state=var, control=button):
                    self._toggle_chip(c, v, state.get())
                    selected = self.model.current.filters.get(c, set())
                    control.configure(text=f"{c.title()}: {len(selected) if selected else 'All'}")
                menu.add_checkbutton(label=value, variable=var, command=toggle)

    def _toggle_chip(self, category: str, value: str, on: bool) -> None:
        self.model.current.toggle_filter(category, value, on)
        self._render()

    # ---- rendering ---------------------------------------------------------
    def _retry(self) -> None:
        self.model.current.error = None
        self._fetch(self.model.selected)

    def _render(self, *, reset_scroll: bool = True) -> None:
        old_voice = self._selected_voice()
        old_id = old_voice.voice_id if old_voice and not reset_scroll else None
        y = self.tree.yview()[0]
        self._cancel_confirm()
        children = self.tree.get_children()
        if children:
            self.tree.delete(*children)
        self._voices.clear()
        self.tree.heading("name", text="Voice")
        self._selection = None
        self.retry_button.pack_forget()
        tab = self.model.current
        label = tab_label(tab.provider)
        self._set_footer("", FG_DIM)
        if tab.loading:
            self._set_footer(f"Loading {label} voices…")
        elif tab.error:
            self._set_footer(tab.error, DANGER)
            self.retry_button.pack(side="bottom", anchor="w", before=self.assign_button.master)
        elif tab.loaded:
            shown = tab.visible(self.search_var.get(), self.host.favorites())
            favorites = set(self.host.favorites())
            current = self.host.speaker_voice_id(self.target) if self.target else ""
            current_provider = self.host.speaker_provider(self.target) if self.target else ""
            for voice in shown:
                self._voices[voice.voice_id] = voice
                status = []
                if voice.voice_id in favorites:
                    status.append("★")
                if voice.voice_id == current and tab.provider == current_provider:
                    status.append("In use")
                self.tree.insert("", "end", iid=voice.voice_id,
                                 values=(voice.name, voice.description, " ".join(status)))
            if shown:
                selected = old_id if old_id in self._voices else (
                    current if current_provider == tab.provider and current in self._voices
                    else shown[0].voice_id)
                self.tree.selection_set(selected)
                self.tree.focus(selected)
                if reset_scroll:
                    self.tree.see(selected)
                else:
                    self.tree.yview_moveto(y)
                self._selection = selected
                self.tree.heading("name", text=f"Voice ({len(shown)})")
            else:
                self._set_footer("No voices match. Clear the search or a filter."
                                 if tab.voices else f"{label} has no voices on this account.")
        self._sync_actions()

    def _set_footer(self, text: str, color: str = FG_DIM) -> None:
        self.footer.configure(text=text, fg=color)
        if text:
            self.footer.pack(side="bottom", fill="x", pady=(6, 0),
                             before=self.assign_button.master)
        else:
            self.footer.pack_forget()

    # ---- assign with confirm ----------------------------------------------
    def _assign_clicked(self, provider: str, voice: Voice) -> None:
        if not self.target:
            self._set_footer("Choose a speaker in “Assign to” first.", DANGER)
            return
        key = (provider, voice.voice_id, self.target)
        if self._pending == key:
            self._cancel_confirm()
            self.host.assign(self.target, provider, voice)
            self._render(reset_scroll=False)
            self._set_footer(f"Assigned {voice.name} to {self.target}. "
                             "Save the card to keep it.", OK)
            return
        self._cancel_confirm()
        self._pending = key
        switch = self.host.speaker_provider(self.target) != provider
        extra = (f" This switches {self.target} to {tab_label(provider)}." if switch else "")
        self._set_footer(f"Press Assign again to use {voice.name} for {self.target}.{extra}",
                         ACCENT)
        self.assign_button.set_style("primary")
        self.assign_button.set_text("Confirm")
        self._pending_job = self.after(CONFIRM_MS, self._cancel_confirm)

    def _cancel_confirm(self) -> None:
        if self._pending_job is not None:
            self.after_cancel(self._pending_job)
            self._pending_job = None
        if self._pending is None:
            return
        self.assign_button.set_style("ghost")
        self.assign_button.set_text("Assign")
        self._pending = None
        self._set_footer("", FG_DIM)
