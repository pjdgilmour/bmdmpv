# SPDX-License-Identifier: LGPL-2.1-or-later
"""Live track selectors, keyed by mpv track IDs rather than list positions."""
from tkinter import ttk


def label(track):
    parts = [f"#{track['id']}"]
    for key in ('lang', 'title', 'codec'):
        if track.get(key):
            parts.append(str(track[key]).replace('\n', ' '))
    if track.get('audio-channels'):
        parts.append(f"{track['audio-channels']} canais")
    if track.get('forced'):
        parts.append('forçada')
    if track.get('external'):
        parts.append('externa')
    return ' · '.join(parts)


class Tracks:
    def __init__(self, parent, app):
        self.app = app
        self.widgets = {}
        self.ids = {}
        for kind, title in [('audio', 'Trilha de áudio'), ('sub', 'Legenda')]:
            ttk.Label(parent, text=title, style='Muted.TLabel').pack(anchor='w', pady=(10, 4))
            widget = ttk.Combobox(parent, state='disabled', width=35)
            widget.pack(fill='x')
            widget.bind('<<ComboboxSelected>>', lambda e, k=kind: self.choose(k))
            self.widgets[kind] = widget
        self.reset()

    def reset(self):
        self.tracks = []
        self.selected = {'audio': False, 'sub': False}
        self.refresh()

    def property_changed(self, name, value):
        if name == 'track-list':
            self.tracks = [t for t in (value or []) if t.get('type') in self.widgets
                           and type(t.get('id')) is int]
            for kind in self.widgets:
                self.selected[kind] = next((t['id'] for t in self.tracks
                                            if t['type'] == kind and t.get('selected')), False)
        elif name in ('aid', 'sid'):
            self.selected['audio' if name == 'aid' else 'sub'] = value if type(value) is int else False
        else:
            return False
        self.refresh()
        return True

    def refresh(self):
        active = bool(self.app.player and self.app.connected and not self.app.player.stopping.is_set())
        for kind, widget in self.widgets.items():
            tracks = [t for t in self.tracks if t['type'] == kind]
            self.ids[kind] = [False] + [t['id'] for t in tracks]
            off = 'Sem áudio' if kind == 'audio' else 'Desativada'
            widget.configure(values=[off] + [label(t) for t in tracks])
            current = self.selected[kind]
            widget.current(self.ids[kind].index(current) if current in self.ids[kind] else 0)
            allowed = active and bool(tracks)
            if kind == 'audio' and self.app.audio_choices[self.app.audio_combo.current()].ao == 'none':
                allowed = False
            widget.configure(state='readonly' if allowed else 'disabled')
            if not active:
                widget.set('Disponível durante a reprodução')
            elif not tracks:
                widget.set('Sem trilhas de áudio' if kind == 'audio' else 'Sem legendas disponíveis')

    def choose(self, kind):
        widget = self.widgets[kind]
        index = widget.current()
        if str(widget['state']) != 'readonly' or not 0 <= index < len(self.ids[kind]):
            return
        self.app.send('set_property', 'aid' if kind == 'audio' else 'sid', self.ids[kind][index])
