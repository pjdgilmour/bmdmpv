#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Real mpv + Tk track switching; --hardware also verifies HDMI subtitle buffer."""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import tkinter as tk
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--hardware', action='store_true')
parser.add_argument('--app-root', type=Path, default=BASE)
args = parser.parse_args()
sys.path.insert(0, str(args.app_root))
from gui.app import App
from gui.core import Audio, Card, Mode, Player


with tempfile.TemporaryDirectory() as tmp:
    directory = Path(tmp)
    for name, text in [('eng', 'FIRST SUBTITLE'), ('por', 'SEGUNDA LEGENDA')]:
        (directory / (name + '.srt')).write_text('1\n00:00:00,000 --> 00:00:08,000\n' + text + '\n')
    clip = directory / 'tracks.mkv'
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                    '-i', 'color=c=0x202020:size=640x360:rate=25:duration=8',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:duration=8',
                    '-f', 'lavfi', '-i', 'sine=frequency=880:duration=8',
                    '-i', str(directory / 'eng.srt'), '-i', str(directory / 'por.srt'),
                    '-map', '0:v', '-map', '1:a', '-map', '2:a', '-map', '3:s', '-map', '4:s',
                    '-c:v', 'mpeg4', '-c:a', 'aac', '-c:s', 'srt',
                    '-metadata:s:a:0', 'language=eng', '-metadata:s:a:1', 'language=por',
                    '-metadata:s:s:0', 'language=eng', '-metadata:s:s:1', 'language=por', str(clip)], check=True)
    errors = []
    with patch('gui.app.discover_cards', return_value=[Card(0, 'Intensity', [Mode('Hp50', 1920, 1080, 50, '1080p50')])]), \
         patch('gui.app.discover_audio', return_value=[Audio('HDMI', 'decklink')]), \
         patch('gui.app.messagebox.showerror', side_effect=lambda *a, **k: errors.append(a)):
        root = tk.Tk()
        root.withdraw()
        app = App(root, profile_path=directory / 'profiles.json')
        def wait(predicate, timeout=15):
            end = time.monotonic() + timeout
            while not predicate():
                root.update()
                assert not errors, errors
                assert time.monotonic() < end, (app.status.get(), app.diagnostics[-2000:])
                time.sleep(.01)
            root.update()
        def settle():
            end = time.monotonic() + .25
            wait(lambda: time.monotonic() >= end)
        def choose(kind, ident):
            widget = app.tracks.widgets[kind]
            assert str(widget['state']) == 'readonly'
            widget.current(app.tracks.ids[kind].index(ident))
            widget.event_generate('<<ComboboxSelected>>')
            wait(lambda: app.tracks.selected[kind] == ident)
            settle()
        def screenshot(name):
            from PIL import Image
            path = directory / (name + '.png')
            app.send('screenshot-to-file', str(path), 'window')
            def readable():
                try:
                    with Image.open(path) as frame:
                        frame.load()
                    return True
                except (OSError, ValueError):
                    return False
            wait(readable)
            return Image.open(path).convert('RGB')
        try:
            wait(lambda: not app.pending)
            app.add_files([str(clip)])
            wait(lambda: app.media is not None)
            app.mute.set(True)
            # Wrap start without replacing Player's type used by the event loop.
            original_start = Player.start
            def start(player):
                if not args.hardware:
                    player.args = [a.replace('--vo=decklink', '--vo=null').replace('--ao=decklink', '--ao=null') for a in player.args]
                original_start(player)
            with patch.object(Player, 'start', start):
                app.play_pause()
            wait(lambda: len(app.tracks.ids['audio']) == 3 and len(app.tracks.ids['sub']) == 3 and app.position > .2)
            app.play_pause()
            wait(lambda: app.paused)
            current = app.player
            for ident in (2, 1, False, 2):
                choose('audio', ident)
            choose('sub', False)
            if args.hardware:
                plain = screenshot('no-sub')
            choose('sub', 1)
            if args.hardware:
                first = screenshot('first-sub')
            choose('sub', 2)
            if args.hardware:
                from PIL import ImageChops, ImageStat
                second = screenshot('second-sub')
                assert max(ImageStat.Stat(ImageChops.difference(plain, first)).sum) > 10000
                assert max(ImageStat.Stat(ImageChops.difference(first, second)).sum) > 10000
            choose('sub', False)
            if args.hardware:
                assert ImageChops.difference(plain, screenshot('disabled-sub')).getbbox() is None
            assert app.player is current, 'Track switching must not restart mpv'
            app.play_pause()
            wait(lambda: not app.paused)
            choose('audio', 1)
            choose('sub', 1)
            app.stop()
            wait(lambda: app.player is None)
            assert str(app.tracks.widgets['sub']['state']) == 'disabled'
            print('PASS: live GUI audio/subtitle switching, disabled tracks, pause/resume, same player, clean stop'
                  + ('; HDMI subtitle buffer verified' if args.hardware else '; null outputs'))
        finally:
            app.close()
            if app.player:
                app.player.thread.join(10)
                root.update()
