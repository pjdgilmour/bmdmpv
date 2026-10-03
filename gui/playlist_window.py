# SPDX-License-Identifier: LGPL-2.1-or-later
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from .library import read_playlist, write_playlist
from .sources import source_name


class PlaylistWindow:
    def __init__(self, app):
        self.app = app
        self.window = tk.Toplevel(app.root)
        self.window.title('Playlist · bmdmpv')
        self.window.geometry('900x480')
        self.window.minsize(880, 350)
        frame = ttk.Frame(self.window, padding=18)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Playlist', style='Title.TLabel').pack(anchor='w')
        ttk.Label(frame, text='Duplo clique reproduz o item. Pare para editar a lista. O modo automático é recalculado por arquivo.',
                  style='Sub.TLabel', wraplength=830).pack(anchor='w', pady=(8, 14))
        table = ttk.Frame(frame)
        table.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(table, columns=('name', 'path'), show='headings', selectmode='browse')
        self.tree.heading('name', text='Ordem / arquivo')
        self.tree.heading('path', text='Caminho')
        self.tree.column('name', width=260)
        self.tree.column('path', width=520)
        scrollbar = ttk.Scrollbar(table, orient='vertical', command=self.tree.yview)
        scrollbar.pack(side='right', fill='y')
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side='left', fill='both', expand=True)
        self.tree.bind('<Double-1>', lambda e: self.play())
        self.tree.bind('<Return>', lambda e: self.play())
        self.tree.tag_configure('current', foreground='#67dfba')
        buttons = ttk.Frame(frame)
        # Reserve controls before allocating remaining height to the table.
        buttons.pack(side='bottom', fill='x', pady=(14, 0), before=table)
        self.edit_buttons = []
        for label, callback in [('Adicionar…', app.browse), ('Remover', self.remove),
                                ('Subir', lambda: self.move(-1)), ('Descer', lambda: self.move(1)),
                                ('Abrir lista…', self.open)]:
            button = ttk.Button(buttons, text=label, command=callback)
            button.pack(side='left', padx=(0, 6))
            self.edit_buttons.append(button)
        ttk.Button(buttons, text='Salvar lista…', command=self.save).pack(side='left')
        ttk.Button(buttons, text='Reproduzir', style='Accent.TButton', command=self.play).pack(side='right')
        self.refresh()

    def exists(self):
        return self.window.winfo_exists()

    def selected(self):
        selected = self.tree.selection()
        return int(selected[0]) if selected else self.app.playlist.index

    def refresh(self, selected=None):
        if not self.exists():
            return
        if selected is None:
            selected = self.selected()
        self.tree.delete(*self.tree.get_children())
        for i, path in enumerate(self.app.playlist.paths):
            current = i == self.app.playlist.index
            label = f'{"▶ " if current else ""}{i + 1:02}  {self.app.source_titles.get(path) or source_name(path)}'
            self.tree.insert('', 'end', iid=str(i), values=(label, path), tags=('current',) if current else ())
        if selected is not None and 0 <= selected < len(self.app.playlist.paths):
            self.tree.selection_set(str(selected))
            self.tree.see(str(selected))
        for button in self.edit_buttons:
            button.state(['disabled'] if self.app.busy() else ['!disabled'])

    def play(self):
        index = self.selected()
        if 0 <= index < len(self.app.playlist.paths):
            self.app.select_item(index, autoplay=True)

    def remove(self):
        if self.app.busy():
            return
        index = self.selected()
        if not 0 <= index < len(self.app.playlist.paths):
            return
        current = index == self.app.playlist.index
        self.app.playlist.remove(index)
        if current:
            self.app.select_item(self.app.playlist.index, autoplay=False)
        self.app.refresh_playlist()

    def move(self, delta):
        if self.app.busy():
            return
        index = self.selected()
        if 0 <= index < len(self.app.playlist.paths):
            selected = self.app.playlist.move(index, delta)
            self.app.refresh_playlist()
            self.refresh(selected)

    def open(self):
        if self.app.busy():
            return
        path = filedialog.askopenfilename(parent=self.window, title='Abrir playlist',
                                          filetypes=[('Playlist UTF-8', '*.m3u8 *.m3u'), ('Todos', '*')])
        if path:
            try:
                playlist = read_playlist(path)
                self.app.replace_playlist(playlist)
            except (OSError, ValueError, UnicodeError) as exc:
                messagebox.showerror('Playlist inválida', str(exc), parent=self.window)

    def save(self):
        path = filedialog.asksaveasfilename(parent=self.window, title='Salvar playlist',
                                           defaultextension='.m3u8', filetypes=[('Playlist UTF-8', '*.m3u8')])
        if path:
            try:
                write_playlist(path, self.app.playlist)
            except (OSError, ValueError) as exc:
                messagebox.showerror('Playlist não salva', str(exc), parent=self.window)
