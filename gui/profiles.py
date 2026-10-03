# SPDX-License-Identifier: LGPL-2.1-or-later
"""Profile controls; applying a profile validates every device before changing UI."""
from tkinter import messagebox, simpledialog, ttk

from .library import validate_profile


class Profiles:
    def __init__(self, parent, app, store):
        self.app, self.store = app, store
        row = ttk.Frame(parent)
        row.pack(fill='x', pady=(0, 12))
        ttk.Label(row, text='Perfil', style='Sub.TLabel').pack(side='left', padx=(0, 10))
        self.combo = ttk.Combobox(row, state='readonly', width=26)
        self.combo.pack(side='left', fill='x', expand=True)
        app.widgets_locked.append(self.combo)
        for label, callback in [('Aplicar', self.apply), ('Salvar perfil…', self.save), ('Excluir', self.delete)]:
            button = ttk.Button(row, text=label, command=callback)
            button.pack(side='left', padx=(8, 0))
            app.widgets_locked.append(button)
        self.refresh()

    def refresh(self, selected=None):
        try:
            self.profiles = self.store.read()
        except (OSError, ValueError) as exc:
            self.profiles = {}
            self.app.diagnostics += str(exc) + '\n'
        self.combo.configure(values=sorted(self.profiles))
        if selected in self.profiles:
            self.combo.set(selected)
        elif self.combo.get() not in self.profiles:
            self.combo.set('')

    def snapshot(self):
        from .app import DECODERS, FRAMING, REPEATS, TARGETS
        app = self.app
        card = app.card()
        if not card:
            raise ValueError('Selecione uma placa disponível antes de salvar o perfil.')
        mode_index = app.mode_combo.current()
        if mode_index < 0:
            raise ValueError('Selecione um formato HDMI válido.')
        audio = app.audio_choices[app.audio_combo.current()]
        target = TARGETS[app.target_combo.get()]
        return validate_profile({
            'card_index': card.index, 'card_name': card.name,
            'target': 'auto' if target is None else str(target),
            'mode': card.modes[mode_index].code,
            'audio_ao': audio.ao, 'audio_device': audio.device,
            'framing': FRAMING[app.framing_combo.get()], 'volume': app.volume.get(),
            'mute': app.mute.get(), 'delay': float(app.delay.get().replace(',', '.')),
            'repeat': REPEATS[app.repeat_combo.get()], 'hwdec': DECODERS[app.decoder_combo.get()]})

    def apply_data(self, profile):
        from .app import DECODERS, FRAMING, REPEATS, TARGETS
        app = self.app
        if app.busy() or app.pending & {'cards', 'audio'}:
            raise ValueError('Pare a reprodução e aguarde a consulta das saídas para aplicar um perfil.')
        p = validate_profile(profile)
        matches = [i for i, c in enumerate(app.cards) if c.name == p['card_name']]
        index = next((i for i in matches if app.cards[i].index == p['card_index']), None)
        if index is None and len(matches) == 1:
            index = matches[0]
        if index is None:
            raise ValueError('A placa salva no perfil não está disponível ou sua identificação é ambígua.')
        card = app.cards[index]
        mode_index = next((i for i, m in enumerate(card.modes) if m.code == p['mode']), None)
        if p['target'] == 'manual' and mode_index is None:
            raise ValueError('O modo HDMI salvo não está disponível nessa placa.')
        if p['target'].isdigit() and not any(m.height == int(p['target']) for m in card.modes):
            raise ValueError('A resolução salva não está disponível nessa placa.')
        audio_index = next((i for i, a in enumerate(app.audio_choices)
                            if a.ao == p['audio_ao'] and a.device == p['audio_device']), None)
        if audio_index is None:
            raise ValueError('A saída de áudio salva não está disponível. Atualize as saídas ou escolha outro perfil.')
        # All checks passed. Never silently reroute missing devices.
        app.card_combo.current(index)
        app.card_changed()
        app.mode_combo.current(mode_index if mode_index is not None else 0)
        app.target_combo.set(next(k for k, v in TARGETS.items() if ('auto' if v is None else str(v)) == p['target']))
        app.audio_combo.current(audio_index)
        for widget, choices, key in [(app.framing_combo, FRAMING, 'framing'),
                                     (app.decoder_combo, DECODERS, 'hwdec'),
                                     (app.repeat_combo, REPEATS, 'repeat')]:
            widget.set(next(k for k, v in choices.items() if v == p[key]))
        app.volume.set(p['volume'])
        app.set_volume(p['volume'])
        app.mute.set(p['mute'])
        app.delay.set(f"{p['delay']:.3f}")
        app.decoder_changed()
        app.repeat_changed()
        app.update_mode()

    def apply(self):
        try:
            self.profiles = self.store.read()
            name = self.combo.get()
            if name not in self.profiles:
                raise ValueError('Selecione um perfil salvo.')
            self.apply_data(self.profiles[name])
            self.app.status.set('Perfil aplicado: ' + name)
        except (OSError, ValueError) as exc:
            messagebox.showerror('Perfil não aplicado', str(exc), parent=self.app.root)

    def save(self):
        if self.app.busy():
            return
        try:
            profile = self.snapshot()
            name = simpledialog.askstring('Salvar perfil', 'Nome do perfil (um existente será atualizado):',
                                          initialvalue=self.combo.get(), parent=self.app.root)
            if name is not None:
                name = self.store.save(name, profile)
                self.refresh(name)
                self.app.status.set('Perfil salvo: ' + name)
        except (OSError, ValueError) as exc:
            messagebox.showerror('Perfil não salvo', str(exc), parent=self.app.root)

    def delete(self):
        if self.app.busy():
            return
        name = self.combo.get()
        if name and messagebox.askyesno('Excluir perfil', f'Excluir o perfil “{name}”?', parent=self.app.root):
            try:
                self.store.delete(name)
                self.refresh()
            except (OSError, ValueError) as exc:
                messagebox.showerror('Perfil não excluído', str(exc), parent=self.app.root)
