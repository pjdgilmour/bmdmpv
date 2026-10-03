# SPDX-License-Identifier: LGPL-2.1-or-later
"""Desktop controller for the local mpv DeckLink build (Python 3 + Tk)."""
import argparse
from pathlib import Path
import queue
import shlex
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from .core import (BASE, Audio, Player, choose_mode, discover_audio, discover_cards,
                   mode_note, playback_args, probe_media)
from .library import Playlist, ProfileStore, read_playlist
from .playlist_window import PlaylistWindow
from .profiles import Profiles
from .sources import is_remote, normalize_source, youtube_url
from .youtube import BROWSERS, ProbeCancelled

TARGETS = {'Automático · priorizar FPS': None, 'HD · 720p': 720,
           'Full HD · 1080p': 1080, 'Ultra HD · 2160p': 2160, 'Modo manual': 'manual'}
FRAMING = {'Ajustar · preservar imagem': 'fit', 'Preencher · cortar bordas': 'fill',
           'Esticar · ocupar toda a tela': 'stretch'}
DECODERS = {'CPU': 'no', 'GPU · automática': 'auto-copy',
            'NVIDIA · NVDEC': 'nvdec-copy', 'Intel / AMD · VA-API': 'vaapi-copy'}
REPEATS = {'Não repetir': 'none', 'Repetir arquivo': 'file', 'Repetir playlist': 'playlist'}
BG, PANEL, FG, MUTED, ACCENT = '#11171d', '#1c252e', '#edf2f6', '#a5b4c2', '#67dfba'


def timestamp(seconds):
    seconds = max(0, int(seconds or 0))
    return f'{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}'


class App:
    def __init__(self, root, initial_file=None, profile_path=None):
        self.root = root
        self.events = queue.Queue()
        self.cards = []
        self.audio_choices = [Audio('Intensity / Blackmagic · HDMI', 'decklink'), Audio('Sem áudio', 'none')]
        self.media = None
        self.mode = None
        self.player = None
        self.closing = False
        self.generation = 0
        self.pending = set()
        self.playlist = Playlist()
        self.playlist_window = None
        self.profile_store = ProfileStore(profile_path)
        self.switch_to = None
        self.autoplay_generation = None
        self.media_cancel = None
        self.source_titles = {}
        self.duration = 0
        self.position = 0
        self.dragging = False
        self.paused = False
        self.eof = False
        self.connected = False
        self.diagnostics = ''
        self.last_command = ''
        self.widgets_locked = []
        self.path = tk.StringVar(value='Nenhum arquivo selecionado')
        self.info = tk.StringVar(value='Escolha um vídeo ou arquivo de áudio para começar.')
        self.note = tk.StringVar(value='O formato de saída será sugerido a partir do arquivo.')
        self.status = tk.StringVar(value='Consultando dispositivos…')
        self.clock = tk.StringVar(value='00:00:00 / 00:00:00')
        self.route = tk.StringVar(value='Saída HDMI · SDR / 8 bits')
        self.volume = tk.DoubleVar(value=80)
        self.volume_label = tk.StringVar(value='80%')
        self.mute = tk.BooleanVar(value=False)
        self.prefer_high_refresh = tk.BooleanVar(value=True)
        self.decoding = tk.StringVar(value='Decodificação: CPU · redimensionamento na CPU')
        self.delay = tk.StringVar(value='0.000')
        self._theme()
        self._build()
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.bind('<Control-o>', lambda e: self.browse() if not self.player else None)
        root.bind('<Escape>', lambda e: self.stop())
        self.poll_id = root.after(50, self.poll)
        self.refresh()
        if initial_file:
            if not is_remote(initial_file) and Path(initial_file).suffix.lower() in ('.m3u', '.m3u8'):
                try:
                    self.replace_playlist(read_playlist(initial_file))
                except (OSError, ValueError) as exc:
                    messagebox.showerror('Playlist inválida', str(exc))
            else:
                try:
                    self.load(initial_file)
                except ValueError as exc:
                    messagebox.showerror('Fonte inválida', str(exc))

    def _theme(self):
        self.root.title('bmdmpv · Player HDMI')
        self.root.geometry('1060x980')
        self.root.minsize(880, 650)
        self.root.configure(bg=BG)
        self.root.option_add('*TCombobox*Listbox.background', PANEL)
        self.root.option_add('*TCombobox*Listbox.foreground', FG)
        self.root.option_add('*TCombobox*Listbox.selectBackground', '#34584f')
        self.root.option_add('*TCombobox*Listbox.selectForeground', FG)
        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('.', background=BG, foreground=FG, borderwidth=0, font=('Sans', 10))
        style.configure('TFrame', background=BG)
        style.configure('Card.TFrame', background=PANEL)
        style.configure('TLabel', background=PANEL, foreground=FG)
        style.configure('Muted.TLabel', foreground=MUTED)
        style.configure('Note.TLabel', foreground=ACCENT)
        style.configure('Title.TLabel', background=BG, font=('Sans', 25, 'bold'))
        style.configure('Sub.TLabel', background=BG, foreground=MUTED)
        style.configure('Heading.TLabel', font=('Sans', 12, 'bold'))
        style.configure('TButton', background='#2d3b48', foreground=FG, padding=(13, 9))
        style.map('TButton', background=[('active', '#405467'), ('disabled', '#26313b')],
                  foreground=[('disabled', '#82909b')])
        style.configure('Accent.TButton', background=ACCENT, foreground=BG, font=('Sans', 11, 'bold'))
        style.map('Accent.TButton', background=[('active', '#95edcf'), ('disabled', '#304f48')],
                  foreground=[('disabled', '#93afa6')])
        style.configure('TCombobox', fieldbackground='#263441', background='#344655',
                        foreground=FG, arrowcolor=FG, padding=7)
        style.map('TCombobox', fieldbackground=[('readonly', '#263441'), ('disabled', '#242e37')],
                  foreground=[('disabled', '#8999a6')], selectbackground=[('readonly', '#263441')],
                  selectforeground=[('readonly', FG)])
        style.configure('TSpinbox', fieldbackground='#263441', foreground=FG,
                        arrowcolor=FG, background='#344655', padding=6)
        style.configure('TCheckbutton', background=PANEL, foreground=FG, padding=4)
        style.map('TCheckbutton', background=[('active', PANEL)])
        style.configure('Horizontal.TScale', background=PANEL, troughcolor='#344655')
        style.configure('Time.TLabel', font=('Monospace', 11), foreground=MUTED)
        style.configure('Treeview', background=PANEL, fieldbackground=PANEL, foreground=FG, rowheight=30)
        style.map('Treeview', background=[('selected', '#34584f')], foreground=[('selected', FG)])
        style.configure('Treeview.Heading', background='#2d3b48', foreground=FG, padding=7)

    def panel(self, parent, title):
        panel = ttk.Frame(parent, style='Card.TFrame', padding=18)
        ttk.Label(panel, text=title, style='Heading.TLabel').pack(anchor='w', pady=(0, 14))
        return panel

    def combo(self, parent, label, values, on_change=None):
        ttk.Label(parent, text=label, style='Muted.TLabel').pack(anchor='w', pady=(0, 5))
        widget = ttk.Combobox(parent, values=values, state='readonly')
        widget.pack(fill='x', pady=(0, 12))
        if values:
            widget.current(0)
        if on_change:
            widget.bind('<<ComboboxSelected>>', on_change)
        self.widgets_locked.append(widget)
        return widget

    def _build(self):
        canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.root, orient='vertical', command=canvas.yview)
        scrollbar.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        canvas.configure(yscrollcommand=scrollbar.set)
        outer = ttk.Frame(canvas, padding=24)
        content = canvas.create_window((0, 0), window=outer, anchor='nw')
        outer.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(content, width=e.width))
        header = ttk.Frame(outer)
        header.pack(fill='x', pady=(0, 20))
        ttk.Label(header, text='bmdmpv', style='Title.TLabel').pack(side='left')
        ttk.Label(header, text='PLAYER HDMI\nBlackmagic Intensity Pro 4K', style='Sub.TLabel',
                  justify='right').pack(side='right')
        self.profiles = Profiles(outer, self, self.profile_store)
        filepanel = self.panel(outer, '01  /  Arquivo')
        filepanel.pack(fill='x', pady=(0, 12))
        row = ttk.Frame(filepanel, style='Card.TFrame')
        row.pack(fill='x')
        self.playlist_button = ttk.Button(row, text='Playlist (0)', command=self.show_playlist)
        self.playlist_button.pack(side='right')
        self.youtube_button = ttk.Button(row, text='YouTube…', command=self.add_youtube)
        self.youtube_button.pack(side='right', padx=(8, 0))
        self.widgets_locked.append(self.youtube_button)
        self.open_button = ttk.Button(row, text='Adicionar arquivos…', command=self.browse)
        self.open_button.pack(side='right', padx=(12, 0))
        self.widgets_locked.append(self.open_button)
        path_label = ttk.Label(row, textvariable=self.path, wraplength=440)
        path_label.pack(side='left', fill='x', expand=True)
        path_label.bind('<Configure>', lambda e: path_label.configure(wraplength=max(100, e.width)))
        cookie_row = ttk.Frame(filepanel, style='Card.TFrame')
        cookie_row.pack(fill='x', pady=(10, 0))
        ttk.Label(cookie_row, text='Cookies do YouTube', style='Muted.TLabel').pack(side='left', padx=(0, 10))
        self.browser_combo = ttk.Combobox(cookie_row, values=list(BROWSERS), state='readonly', width=15)
        self.browser_combo.current(0)
        self.browser_combo.pack(side='left')
        self.browser_combo.bind('<<ComboboxSelected>>', self.browser_changed)
        self.widgets_locked.append(self.browser_combo)
        ttk.Label(cookie_row, text='Use o navegador conectado à sua conta.',
                  style='Muted.TLabel').pack(side='left', padx=(10, 0))
        ttk.Label(filepanel, textvariable=self.info, style='Muted.TLabel', wraplength=900).pack(anchor='w', pady=(10, 0))
        outputs = ttk.Frame(outer)
        outputs.pack(fill='x', pady=(0, 12))
        outputs.columnconfigure(0, weight=1, uniform='outputs')
        outputs.columnconfigure(1, weight=1, uniform='outputs')
        video = self.panel(outputs, '02  /  Vídeo')
        video.grid(row=0, column=0, sticky='nsew', padx=(0, 6))
        audio = self.panel(outputs, '03  /  Áudio')
        audio.grid(row=0, column=1, sticky='nsew', padx=(6, 0))
        self.card_combo = self.combo(video, 'Placa de saída', [], self.card_changed)
        self.target_combo = self.combo(video, 'Resolução de saída', list(TARGETS), self.update_mode)
        self.mode_combo = self.combo(video, 'Formato HDMI', [], self.update_mode)
        self.refresh_preference = ttk.Checkbutton(video, text='Preferir 50/60 Hz na HDMI',
                                                  variable=self.prefer_high_refresh, command=self.update_mode)
        self.refresh_preference.pack(anchor='w', pady=(0, 12))
        self.widgets_locked.append(self.refresh_preference)
        self.framing_combo = self.combo(video, 'Enquadramento', list(FRAMING), self.update_mode)
        self.decoder_combo = self.combo(video, 'Decodificação', list(DECODERS), self.decoder_changed)
        ttk.Label(video, textvariable=self.decoding, style='Muted.TLabel', wraplength=445).pack(anchor='w')
        self.audio_combo = self.combo(audio, 'Enviar áudio para', [a.label for a in self.audio_choices])
        ttk.Label(audio, text='Volume', style='Muted.TLabel').pack(anchor='w')
        volume_row = ttk.Frame(audio, style='Card.TFrame')
        volume_row.pack(fill='x', pady=(4, 8))
        ttk.Scale(volume_row, from_=0, to=100, variable=self.volume, command=self.set_volume).pack(side='left', fill='x', expand=True)
        ttk.Label(volume_row, textvariable=self.volume_label, width=5, anchor='e').pack(side='right')
        ttk.Checkbutton(audio, text='Silenciar', variable=self.mute, command=lambda: self.send('set_property', 'mute', self.mute.get())).pack(anchor='w', pady=(0, 16))
        ttk.Label(audio, text='Atraso do áudio (segundos)', style='Muted.TLabel').pack(anchor='w', pady=(0, 5))
        delay_row = ttk.Frame(audio, style='Card.TFrame')
        delay_row.pack(fill='x')
        self.delay_spin = ttk.Spinbox(delay_row, from_=-10, to=10, increment=.01,
                                      textvariable=self.delay, width=10)
        self.delay_spin.pack(side='left')
        ttk.Button(delay_row, text='Aplicar', command=self.set_delay).pack(side='left', padx=8)
        self.delay_spin.bind('<Return>', lambda e: self.set_delay())
        ttk.Label(audio, text='Valor positivo atrasa o áudio.\nA saída padrão acompanha o sistema.',
                  style='Muted.TLabel', wraplength=390).pack(anchor='w', pady=(8, 0))
        summary = ttk.Frame(outer, style='Card.TFrame', padding=(18, 12))
        summary.pack(fill='x', pady=(0, 12))
        ttk.Label(summary, textvariable=self.note, style='Note.TLabel', wraplength=880).pack(anchor='w')
        transport = ttk.Frame(outer, style='Card.TFrame', padding=18)
        transport.pack(fill='x')
        timeline = ttk.Frame(transport, style='Card.TFrame')
        timeline.pack(fill='x')
        self.seek_scale = ttk.Scale(timeline, from_=0, to=1)
        self.seek_scale.pack(side='left', fill='x', expand=True, padx=(0, 16))
        self.seek_scale.state(['disabled'])
        self.seek_scale.bind('<ButtonPress-1>', lambda e: setattr(self, 'dragging', True))
        self.seek_scale.bind('<ButtonRelease-1>', self.seek_release)
        self.seek_scale.bind('<KeyRelease>', self.seek_release)
        ttk.Label(timeline, textvariable=self.clock, style='Time.TLabel').pack(side='right')
        buttons = ttk.Frame(transport, style='Card.TFrame')
        buttons.pack(fill='x', pady=(14, 0))
        self.play_button = ttk.Button(buttons, text='Reproduzir', style='Accent.TButton', command=self.play_pause)
        self.play_button.pack(side='left')
        self.stop_button = ttk.Button(buttons, text='Parar', command=self.stop, state='disabled')
        self.stop_button.pack(side='left', padx=8)
        self.previous_button = ttk.Button(buttons, text='Anterior', command=lambda: self.next_item(-1))
        self.previous_button.pack(side='left')
        self.next_button = ttk.Button(buttons, text='Próximo', command=self.next_item)
        self.next_button.pack(side='left', padx=8)
        self.back_button = ttk.Button(buttons, text='−10 s', command=lambda: self.send('seek', -10, 'relative'), state='disabled')
        self.back_button.pack(side='left')
        self.forward_button = ttk.Button(buttons, text='+10 s', command=lambda: self.send('seek', 10, 'relative'), state='disabled')
        self.forward_button.pack(side='left', padx=8)
        for button in (self.stop_button, self.previous_button, self.next_button,
                       self.back_button, self.forward_button):
            button.configure(width=6)
        self.play_button.configure(width=10)
        self.repeat_combo = ttk.Combobox(buttons, values=list(REPEATS), state='readonly', width=19)
        self.repeat_combo.current(0)
        self.repeat_combo.pack(side='right')
        self.repeat_combo.bind('<<ComboboxSelected>>', self.repeat_changed)
        footer = ttk.Frame(outer)
        footer.pack(fill='x', pady=(14, 0))
        self.refresh_button = ttk.Button(footer, text='Atualizar saídas', command=self.refresh)
        self.refresh_button.pack(side='right')
        ttk.Button(footer, text='Diagnóstico', command=self.show_diagnostics).pack(side='right', padx=8)
        ttk.Label(footer, textvariable=self.status, style='Sub.TLabel', wraplength=560).pack(side='left', fill='x')
        ttk.Label(outer, textvariable=self.route, style='Sub.TLabel').pack(anchor='w', pady=(8, 0))
        self.refresh_playlist()

    def job(self, name, fn, daemon=True):
        self.pending.add(name)
        def worker():
            try:
                self.events.put((name, 'result', fn()))
            except ProbeCancelled:
                self.events.put((name, 'cancelled', None))
            except Exception as exc:
                self.events.put((name, 'error', str(exc)))
        threading.Thread(target=worker, daemon=daemon).start()

    def refresh(self):
        if self.busy() or 'cards' in self.pending or 'audio' in self.pending:
            return
        self.refresh_button.state(['disabled'])
        self.status.set('Consultando placa e interfaces de áudio…')
        self.job('cards', discover_cards)
        self.job('audio', discover_audio)

    def browse(self):
        if self.busy():
            return
        paths = filedialog.askopenfilenames(title='Adicionar mídia à playlist', filetypes=[
            ('Vídeo e áudio', '*.mkv *.mp4 *.mov *.mxf *.avi *.webm *.m4v *.ts *.wav *.flac *.mp3 *.aac *.ogg'),
            ('Todos os arquivos', '*')])
        if paths:
            self.add_files(paths)

    def busy(self):
        return self.player is not None or self.switch_to is not None or self.autoplay_generation is not None

    def add_youtube(self):
        if self.busy():
            return
        value = simpledialog.askstring('Abrir YouTube', 'Cole o link de um vídeo do YouTube:', parent=self.root)
        if value is None:
            return
        try:
            source = youtube_url(value)
        except ValueError as exc:
            messagebox.showerror('Link inválido', str(exc), parent=self.root)
            return
        self.playlist.append([source])
        self.select_item(len(self.playlist.paths) - 1)

    def browser_changed(self, event=None):
        if not self.busy() and self.playlist.index >= 0:
            path = self.playlist.paths[self.playlist.index]
            if is_remote(path):
                self._load_entry(path)

    def show_playlist(self):
        if self.playlist_window and self.playlist_window.exists():
            self.playlist_window.window.lift()
        else:
            self.playlist_window = PlaylistWindow(self)

    def refresh_playlist(self):
        self.playlist_button.configure(text=f'Playlist ({len(self.playlist.paths)})')
        self.previous_button.state(['!disabled'] if self.playlist.adjacent(-1) is not None else ['disabled'])
        self.next_button.state(['!disabled'] if self.playlist.adjacent(1, REPEATS[self.repeat_combo.get()] == 'playlist') is not None else ['disabled'])
        if self.playlist_window:
            self.playlist_window.refresh()

    def add_files(self, paths):
        if self.busy():
            return
        was_empty = not self.playlist.paths
        self.playlist.append(paths)
        if was_empty and self.playlist.paths:
            self.select_item(0)
        self.refresh_playlist()

    def replace_playlist(self, playlist):
        if self.busy():
            return
        self.playlist = playlist
        self.select_item(playlist.index)

    def select_item(self, index, autoplay=False):
        if self.closing:
            return
        self.autoplay_generation = None
        if not 0 <= index < len(self.playlist.paths):
            if self.player:
                return
            self.generation += 1
            if self.media_cancel:
                self.media_cancel.set()
            self.media = None
            self.path.set('Nenhum arquivo selecionado')
            self.info.set('Adicione arquivos à playlist para começar.')
            self.duration = self.position = 0
            self.clock.set('00:00:00 / 00:00:00')
            self.seek_scale.set(0)
            self.lock(False)
            self.refresh_playlist()
            return
        self.playlist.index = index
        if self.player:
            self.switch_to = (index, autoplay)
            self.stop(transition=True)
        else:
            self._load_entry(self.playlist.paths[index], autoplay)
        self.refresh_playlist()

    def next_item(self, delta=1):
        index = self.playlist.adjacent(delta, REPEATS[self.repeat_combo.get()] == 'playlist')
        if index is not None:
            self.select_item(index, autoplay=self.busy())

    def repeat_changed(self, event=None):
        self.send('set_property', 'loop-file', 'inf' if REPEATS[self.repeat_combo.get()] == 'file' else 'no')
        self.refresh_playlist()

    def decoder_changed(self, event=None):
        self.decoding.set(f'Selecionado: {self.decoder_combo.get()} · escala na CPU')

    def load(self, path):
        self.replace_playlist(Playlist([path]))

    def _load_entry(self, path, autoplay=False):
        if self.media_cancel:
            self.media_cancel.set()
        cancel = threading.Event() if is_remote(path) else None
        self.media_cancel = cancel
        self.generation += 1
        self.autoplay_generation = self.generation if autoplay else None
        self.media = None
        self.path.set(normalize_source(path))
        self.info.set('Consultando o YouTube com yt-dlp…' if cancel else 'Analisando o arquivo…')
        self.lock(self.busy())
        self.update_mode()
        if cancel is not None:
            self.stop_button.state(['!disabled'])
        browser = BROWSERS[self.browser_combo.get()]
        self.job(('media', self.generation),
                 lambda: probe_media(path, cancel, browser=browser) if cancel is not None else probe_media(path),
                 daemon=cancel is None)

    def maybe_autoplay(self):
        if (self.autoplay_generation != self.generation or not self.media or
                self.pending & {'cards', 'audio'} or self.closing):
            return
        self.autoplay_generation = None
        self.lock(False)
        if not self.mode or self.media.unsupported_color:
            self.status.set('Playlist interrompida: arquivo ou saída incompatível')
            messagebox.showerror('Playlist interrompida', self.note.get(), parent=self.root)
            return
        self.play_pause()

    def card_changed(self, event=None):
        card = self.card()
        self.mode_combo.configure(values=[m.label for m in card.modes] if card else [])
        if card:
            self.mode_combo.current(0)
        self.update_mode()

    def card(self):
        index = self.card_combo.current()
        return self.cards[index] if 0 <= index < len(self.cards) else None

    def update_mode(self, event=None):
        manual = TARGETS[self.target_combo.get()] == 'manual'
        self.mode_combo.configure(state='readonly' if manual and not self.player else 'disabled')
        self.mode = None
        card = self.card()
        if card and self.media:
            try:
                self.mode = (card.modes[self.mode_combo.current()] if manual else
                             choose_mode(card.modes, self.media, TARGETS[self.target_combo.get()],
                                         prefer_high_refresh=self.prefer_high_refresh.get()))
                self.mode_combo.set(self.mode.label)
                note = mode_note(self.mode, self.media)
                if FRAMING[self.framing_combo.get()] == 'fill':
                    note += ' · Preenchimento com corte das bordas'
                elif FRAMING[self.framing_combo.get()] == 'stretch':
                    note += ' · Imagem esticada sem preservar proporção'
                if self.media.unsupported_color:
                    note = 'HDR/BT.2020/Dolby Vision: converta o arquivo para SDR antes de reproduzir.'
                self.note.set(note)
            except (ValueError, IndexError) as exc:
                self.note.set(str(exc))
        elif not card:
            self.note.set('Aguardando uma placa com saída HDMI compatível.')
        else:
            self.note.set('Selecione um arquivo para detectar resolução e taxa de quadros.')
        enabled = self.mode and self.media and not self.media.unsupported_color
        self.play_button.state(['!disabled'] if enabled else ['disabled'])

    def current_args(self):
        if not self.media or not self.mode or not self.card():
            raise ValueError('Selecione um arquivo e um modo de saída disponível.')
        return playback_args(self.media, self.card(), self.mode,
                             self.audio_choices[self.audio_combo.current()],
                             FRAMING[self.framing_combo.get()], self.volume.get(),
                             float(self.delay.get().replace(',', '.')),
                             REPEATS[self.repeat_combo.get()] == 'file', self.mute.get(),
                             DECODERS[self.decoder_combo.get()])

    def play_pause(self):
        if self.player:
            if self.eof:
                self.send('seek', 0, 'absolute+exact')
                self.send('set_property', 'pause', False)
            else:
                self.send('cycle', 'pause')
            return
        try:
            args = self.current_args()
        except ValueError as exc:
            messagebox.showerror('Verifique a configuração', str(exc))
            return
        self.last_command = shlex.join(args)
        self.diagnostics = self.last_command + '\n\n'
        self.player = Player(args, self.events)
        self.connected = False
        self.eof = False
        self.paused = False
        self.position = 0
        self.seek_scale.set(0)
        self.clock.set(f'00:00:00 / {timestamp(self.duration)}')
        self.decoding.set('Consultando decodificador…')
        self.status.set('Abrindo a saída HDMI…')
        self.route.set(f'{self.mode.name} · {self.audio_combo.get()}')
        self.lock(True)
        self.play_button.state(['disabled'])
        self.play_button.configure(text='Abrindo…')
        self.player.start()

    def lock(self, playing):
        for widget in self.widgets_locked:
            if isinstance(widget, ttk.Combobox):
                widget.configure(state='disabled' if playing else 'readonly')
            else:
                widget.state(['disabled'] if playing else ['!disabled'])
        self.refresh_button.state(['disabled'] if playing or self.pending & {'cards', 'audio'} else ['!disabled'])
        self.stop_button.state(['!disabled'] if playing else ['disabled'])
        for widget in (self.back_button, self.forward_button, self.seek_scale):
            widget.state(['!disabled'] if playing and self.connected else ['disabled'])
        if not playing:
            self.update_mode()
        self.refresh_playlist()

    def send(self, *args):
        if self.player and self.connected and not self.player.stopping.is_set():
            self.player.command(*args)

    def set_volume(self, value):
        self.volume_label.set(f'{float(value):.0f}%')
        self.send('set_property', 'volume', float(value))

    def set_delay(self):
        try:
            value = float(self.delay.get().replace(',', '.'))
            if not -10 <= value <= 10:
                raise ValueError()
        except ValueError:
            messagebox.showerror('Atraso do áudio', 'Informe um valor entre −10 e +10 segundos.')
            return
        self.delay.set(f'{value:.3f}')
        self.send('set_property', 'audio-delay', value)

    def seek_release(self, event=None):
        if self.player and self.connected:
            self.send('seek', self.seek_scale.get(), 'absolute+exact')
        self.dragging = False

    def stop(self, transition=False):
        if not transition:
            if self.media_cancel:
                self.media_cancel.set()
            self.autoplay_generation = None
            if self.switch_to:
                self.switch_to = (self.switch_to[0], False)
        if self.player:
            self.status.set('Encerrando e liberando a placa…')
            self.play_button.state(['disabled'])
            self.stop_button.state(['disabled'])
            self.player.stop()
        else:
            self.lock(False)

    def close(self):
        self.closing = True
        if self.media_cancel:
            self.media_cancel.set()
        self.switch_to = None
        self.autoplay_generation = None
        if self.player:
            self.stop()
        else:
            self.destroy()

    def destroy(self):
        if self.poll_id is not None:
            self.root.after_cancel(self.poll_id)
            self.poll_id = None
        self.root.destroy()

    def property_changed(self, name, value):
        if value is None:
            return
        if name == 'duration':
            self.duration = value
            self.seek_scale.configure(to=max(1, value))
        elif name == 'time-pos':
            self.position = value
            if not self.dragging:
                self.seek_scale.set(value)
        elif name == 'pause':
            self.paused = value
        elif name == 'eof-reached':
            self.eof = value
            if value and not self.player.stopping.is_set():
                index = self.playlist.adjacent(1, REPEATS[self.repeat_combo.get()] == 'playlist')
                if index is not None:
                    self.select_item(index, autoplay=True)
                    return
        elif name == 'volume':
            self.volume.set(value)
            self.volume_label.set(f'{value:.0f}%')
        elif name == 'mute':
            self.mute.set(value)
        elif name == 'hwdec-current':
            actual = 'CPU' if value in ('', 'no') else 'GPU · ' + value
            if value in ('', 'no') and DECODERS[self.decoder_combo.get()] != 'no':
                actual += ' (GPU não utilizada neste arquivo)'
            self.decoding.set(f'{actual} · redimensionamento na CPU')
        if name in ('pause', 'eof-reached', 'time-pos') and not self.player.stopping.is_set():
            self.status.set('Fim do arquivo' if self.eof else 'Pausado' if self.paused else 'Reproduzindo pela HDMI')
            self.play_button.configure(text='Reiniciar' if self.eof else 'Continuar' if self.paused else 'Pausar')
        self.clock.set(f'{timestamp(self.position)} / {timestamp(self.duration)}')

    def poll(self):
        self.poll_id = None
        for _ in range(300):
            try:
                source, kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if isinstance(source, Player):
                if source is not self.player:
                    continue
                if kind == 'connected':
                    self.connected = True
                    if not self.player.stopping.is_set():
                        self.lock(True)
                        self.play_button.state(['!disabled'])
                elif kind == 'property':
                    self.property_changed(*value)
                elif kind == 'command-error':
                    self.diagnostics += '\nComando IPC: ' + value
                    self.status.set('Comando não aplicado: ' + value)
                elif kind == 'finished':
                    self.diagnostics += value['log']
                    error = value['error'] or (f"mpv encerrou com código {value['code']}." if value['code'] else '')
                    self.player = None
                    self.connected = False
                    transition, self.switch_to = self.switch_to, None
                    self.lock(False)
                    self.play_button.configure(text='Reproduzir')
                    self.status.set('Falha na reprodução · abra Diagnóstico' if error else 'Parado · placa liberada')
                    if error:
                        self.diagnostics += '\n' + error
                        if not self.closing:
                            hint = ('Confira o Diagnóstico, a conexão e o yt-dlp. O YouTube pode recusar o stream mesmo após fornecer seus metadados.'
                                    if self.media and self.media.ytdl_format else
                                    'Confira o Diagnóstico. Feche outros aplicativos que estejam usando a placa.')
                            messagebox.showerror('Não foi possível reproduzir', error + '\n\n' + hint)
                    if self.closing:
                        self.destroy()
                        return
                    if transition and not error:
                        self.select_item(transition[0], autoplay=transition[1])
            else:
                self.pending.discard(source)
                if isinstance(source, tuple) and source != ('media', self.generation):
                    continue
                if kind == 'cancelled':
                    self.autoplay_generation = None
                    self.info.set('Consulta cancelada. Selecione o item na playlist para tentar novamente.')
                    self.status.set('Consulta cancelada')
                    self.lock(False)
                elif kind == 'error':
                    self.diagnostics += f'\n{source}: {value}\n'
                    self.status.set('Falha ao consultar arquivo/dispositivos · veja Diagnóstico')
                    if isinstance(source, tuple):
                        self.autoplay_generation = None
                        self.lock(False)
                        self.info.set('Não foi possível analisar o arquivo.')
                        if not self.closing:
                            messagebox.showerror('Arquivo inválido', value)
                elif source == 'cards':
                    selected = self.card_combo.get()
                    self.cards = value
                    self.card_combo.configure(values=[c.label for c in value])
                    self.card_combo.set(selected if selected in [c.label for c in value] else value[0].label if value else '')
                    self.card_changed()
                    self.status.set('Pronto' if value else 'Nenhuma saída HDMI compatível encontrada')
                elif source == 'audio':
                    selected = self.audio_combo.get()
                    self.audio_choices = value
                    self.audio_combo.configure(values=[a.label for a in value])
                    self.audio_combo.set(selected if selected in [a.label for a in value] else value[0].label)
                else:
                    self.media = value
                    self.media_cancel = None
                    if value.title:
                        self.source_titles[value.path] = value.title
                        self.path.set(value.title + '\n' + value.path)
                        self.refresh_playlist()
                    self.duration = value.duration
                    self.position = 0
                    details = (f'{value.width:g} × {value.height:g} · {value.fps:.3f} fps' if value.video else 'Somente áudio')
                    self.info.set(f'{details} · {timestamp(value.duration)} · {"Com áudio" if value.audio else "Sem faixa de áudio"}')
                    self.clock.set(f'00:00:00 / {timestamp(value.duration)}')
                    self.seek_scale.configure(to=max(1, self.duration))
                    self.seek_scale.set(0)
                    self.stop_button.state(['disabled'])
                    self.update_mode()
                self.maybe_autoplay()
                if not self.player and not self.pending & {'cards', 'audio'}:
                    self.refresh_button.state(['!disabled'])
        self.poll_id = self.root.after(50, self.poll)

    def show_diagnostics(self):
        window = tk.Toplevel(self.root)
        window.title('Diagnóstico · bmdmpv')
        window.geometry('850x500')
        frame = ttk.Frame(window, padding=14)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='O log completo da sessão aparece aqui após Parar.', style='Sub.TLabel').pack(anchor='w', pady=(0, 10))
        text = tk.Text(frame, bg=BG, fg=FG, insertbackground=FG, wrap='word', font=('Monospace', 10))
        text.pack(fill='both', expand=True)
        text.insert('1.0', self.diagnostics or 'Nenhum erro registrado.')
        text.configure(state='disabled')
        row = ttk.Frame(frame)
        row.pack(fill='x', pady=(10, 0))
        def copy():
            self.root.clipboard_clear()
            self.root.clipboard_append(self.last_command)
        def save():
            path = filedialog.asksaveasfilename(parent=window, title='Salvar diagnóstico', defaultextension='.log', initialfile='bmdmpv.log')
            if path:
                try:
                    Path(path).write_text(self.diagnostics, encoding='utf-8')
                except OSError as exc:
                    messagebox.showerror('Erro ao salvar', str(exc), parent=window)
        ttk.Button(row, text='Copiar comando', command=copy).pack(side='left')
        ttk.Button(row, text='Salvar log…', command=save).pack(side='left', padx=8)
        ttk.Button(row, text='Fechar', command=window.destroy).pack(side='right')


def main():
    parser = argparse.ArgumentParser(description='Player gráfico para a saída Blackmagic HDMI.')
    parser.add_argument('arquivo', nargs='?', help='Arquivo, link do YouTube ou playlist M3U8 (sem reprodução automática).')
    args = parser.parse_args()
    root = tk.Tk()
    App(root, args.arquivo)
    root.mainloop()


if __name__ == '__main__':
    main()
