#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Explicit online test: public YouTube video → GUI → Intensity, muted audio."""
import argparse
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
from unittest.mock import patch
from PIL import Image, ImageStat
TEST_BASE = Path(__file__).resolve().parents[1]
bootstrap = argparse.ArgumentParser(add_help=False)
bootstrap.add_argument('--app-root', type=Path, default=TEST_BASE,
                       help='Application directory; use /usr/lib/bmdmpv to test the installed package.')
location, _ = bootstrap.parse_known_args()
sys.path.insert(0, str(location.app_root))
from gui.app import App, messagebox
from gui.core import BASE
from gui.youtube import BROWSERS

parser = argparse.ArgumentParser(parents=[bootstrap])
parser.add_argument('--url', default='https://www.youtube.com/watch?v=aqz-KE-bpKQ')
parser.add_argument('--browser', default='', choices=list(BROWSERS.values()))
parser.add_argument('--cpu', action='store_true')
parser.add_argument('--mode', help='Force an HDMI mode code, e.g. Hp50.')
parser.add_argument('--hold', type=float, default=0, help='Seconds to leave playback running for visual HDMI inspection.')
args = parser.parse_args()
results = TEST_BASE / 'test-results'
results.mkdir(exist_ok=True)
errors = []
messagebox.showerror = lambda *a, **k: errors.append(a)

with tempfile.TemporaryDirectory() as tmp:
    root = tk.Tk()
    app = App(root, profile_path=Path(tmp) / 'profiles.json')
    props = {}
    original = app.property_changed
    def observe(name, value):
        props[name] = value
        original(name, value)
    app.property_changed = observe
    def wait(predicate, timeout=65):
        end = time.monotonic() + timeout
        while not predicate():
            root.update()
            if errors:
                raise AssertionError(errors)
            if time.monotonic() > end:
                raise AssertionError((app.status.get(), props))
            time.sleep(.03)
        root.update()
    try:
        wait(lambda: not app.pending)
        app.browser_combo.set(next(k for k, v in BROWSERS.items() if v == args.browser))
        with patch('gui.app.simpledialog.askstring', return_value=args.url):
            app.youtube_button.invoke()
        wait(lambda: app.media is not None)
        assert app.media.ytdl_format and app.media.title
        assert len(app.playlist.paths) == 1
        assert app.playlist.paths[0].startswith('https://www.youtube.com/watch?v=')
        app.decoder_combo.set('CPU' if args.cpu else 'GPU · automática')
        if args.mode:
            app.target_combo.set('Modo manual')
            app.mode_combo.current(next(i for i, m in enumerate(app.card().modes) if m.code == args.mode))
            app.update_mode()
        app.mute.set(True)
        app.play_button.invoke()
        wait(lambda: props.get('current-vo') == 'decklink' and props.get('current-ao') == 'decklink' and app.position > 1)
        app.play_button.invoke()
        wait(lambda: app.paused)
        app.seek_scale.set(10)
        app.seek_release()
        wait(lambda: abs(app.position - 10) < .25)
        # Capture the actual UYVY output buffer, not merely the controller UI.
        frame_path = results / ('youtube-frame-' + ('cpu' if args.cpu else 'gpu') + '.png')
        frame_path.unlink(missing_ok=True)
        app.send('screenshot-to-file', str(frame_path), 'window')
        def frame_written():
            try:
                with Image.open(frame_path) as frame:
                    frame.load()
                return True
            except (OSError, ValueError):
                return False
        wait(frame_written)
        with Image.open(frame_path) as frame:
            frame.load()
            assert frame.size == (app.mode.width, app.mode.height)
            stats = ImageStat.Stat(frame.convert('RGB'))
            assert max(stats.mean) > 5 and max(stats.stddev) > 5, 'Output buffer appears black/flat'
        app.play_button.invoke()
        wait(lambda: not app.paused and app.position > 10.3)
        if args.hold > 0:
            until = time.monotonic() + args.hold
            wait(lambda: time.monotonic() >= until, timeout=args.hold + 5)
        app.stop_button.invoke()
        wait(lambda: app.player is None)
        (results / 'youtube-hardware.log').write_text(app.diagnostics)
        if not args.browser:
            assert 'youtube-dl succeeded' in app.diagnostics
        assert 'Displayed ' in app.diagnostics
        assert '[e][vo/decklink]' not in app.diagnostics
        assert '[e][ao/decklink]' not in app.diagnostics
        print('PASS: YouTube metadata, native yt-dlp hook, nonblank output buffer → DeckLink SDK, pause/seek/resume/stop (physical monitor not verified)')
        print('Selected:', app.media.ytdl_format, app.mode.label, 'decoder:', props.get('hwdec-current'))
    finally:
        (results / 'youtube-hardware.log').write_text(app.diagnostics)
        app.close()
        if app.player:
            app.player.thread.join(10)
            root.update()
        try:
            root.destroy()
        except tk.TclError:
            pass
