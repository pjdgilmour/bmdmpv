#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Explicit GUI + Intensity + NVIDIA test. Sends synthetic SDR video and muted audio."""
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import tkinter as tk
from PIL import ImageGrab
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gui.app import App, messagebox
from gui.core import BASE
from gui.library import ProfileStore

results = BASE / 'test-results'
results.mkdir(exist_ok=True)
clips = [results / 'playlist-h264.mp4', results / 'playlist-hevc.mp4']
for clip, size, fps, codec in zip(clips, ['1920x1080', '1280x720'], ['30000/1001', '50'], ['libx264', 'libx265']):
    if not clip.exists():
        command = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                   '-i', f'testsrc2=size={size}:rate={fps}:duration=3', '-f', 'lavfi',
                   '-i', 'anullsrc=r=48000:cl=stereo', '-shortest', '-c:a', 'aac',
                   '-c:v', codec, '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
                   '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709']
        if codec == 'libx265':
            command += ['-x265-params', 'log-level=error:pools=2']
        subprocess.run(command + [str(clip)], check=True)
fallback = results / 'playlist-mpeg4.mkv'
if not fallback.exists():
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                    '-i', 'testsrc2=size=1280x720:rate=30:duration=3',
                    '-c:v', 'mpeg4', '-q:v', '5', str(fallback)], check=True)

with tempfile.TemporaryDirectory() as tmp:
    root = tk.Tk()
    errors = []
    messagebox.showerror = lambda *args, **kwargs: errors.append(args)
    app = App(root, profile_path=Path(tmp) / 'profiles.json')
    sessions = []
    props = {}
    original = app.property_changed
    original_events = app.events.put
    def record(event):
        if event[1] == 'finished':
            sessions.append(event[2])
        original_events(event)
    app.events.put = record
    def property_changed(name, value):
        props[name] = value
        original(name, value)
    app.property_changed = property_changed

    def wait_for(predicate, timeout=20):
        end = time.monotonic() + timeout
        while not predicate():
            root.update()
            if errors:
                raise AssertionError((errors, app.diagnostics))
            if time.monotonic() > end:
                raise AssertionError((app.status.get(), app.decoding.get(), props, app.diagnostics))
            time.sleep(.015)
        root.update()

    def screenshot(window, name):
        if not window.winfo_viewable():
            window.wait_visibility()
        window.lift()
        root.update()
        wait_for(lambda: window.winfo_viewable())
        # Let the window manager finish mapping before reading its pixels.
        end = time.monotonic() + .25
        wait_for(lambda: time.monotonic() >= end)
        window.update_idletasks()
        x, y = window.winfo_rootx(), window.winfo_rooty()
        ImageGrab.grab((x, y, x + window.winfo_width(), y + window.winfo_height())).save(results / name)

    try:
        wait_for(lambda: not app.pending)
        app.add_files(clips)
        wait_for(lambda: app.media is not None)
        app.decoder_combo.set('GPU · automática')
        app.mute.set(True)
        app.volume.set(20)
        app.repeat_combo.set('Repetir playlist')
        profile = app.profiles.snapshot()
        app.profile_store.save('HDMI + GPU · teste', profile)
        app.profiles.refresh('HDMI + GPU · teste')
        app.decoder_combo.set('CPU')
        app.profiles.apply_data(ProfileStore(app.profile_store.path).read()['HDMI + GPU · teste'])
        assert app.profiles.snapshot() == profile
        app.show_playlist()
        screenshot(app.playlist_window.window, 'playlist-window.png')
        app.playlist_window.window.withdraw()
        app.play_button.invoke()
        wait_for(lambda: app.connected and app.position > .3 and props.get('hwdec-current') == 'nvdec-copy')
        first = app.player
        assert app.mode.code == 'Hp29'
        screenshot(root, 'playlist-gpu-main.png')
        wait_for(lambda: app.connected and app.player is not first and app.playlist.index == 1 and app.position > .3)
        second = app.player
        assert app.mode.code == 'hp50', app.mode
        assert props['hwdec-current'] == 'nvdec-copy', props
        assert props['current-ao'] == 'decklink', props
        wait_for(lambda: app.connected and app.player is not second and app.playlist.index == 0 and app.position > .3)
        assert app.mode.code == 'Hp29'
        app.repeat_combo.set('Não repetir')
        app.repeat_changed()
        app.stop_button.invoke()
        wait_for(lambda: app.player is None)
        for i, session in enumerate(sessions):
            (results / f'playlist-gpu-{i}.log').write_text(session['log'])
            assert session['code'] == 0 and not session['error'], session
            assert 'Using hardware decoding (nvdec-copy)' in session['log'], session['log']
            assert 'Displayed ' in session['log']
            assert '[e][vo/decklink]' not in session['log']
            assert '[e][ao/decklink]' not in session['log']
        assert len(sessions) == 3, len(sessions)
        print('PASS GPU: H.264 and HEVC used nvdec-copy on Intensity HDMI with HDMI audio')
        print('PASS playlist: automatic Hp29 → hp50 → Hp29, EOF advance and repeat, clean stop')
        print('PASS profiles: persisted and applied video/audio/GPU/volume/mute/repeat')
        # MPEG-4 is outside mpv's default hwdec codec list; CPU use must be visible.
        app.load(fallback)
        wait_for(lambda: app.media is not None)
        props.clear()
        app.play_button.invoke()
        wait_for(lambda: app.connected and app.position > .3 and props.get('hwdec-current') == 'no')
        assert 'CPU' in app.decoding.get()
        app.stop_button.invoke()
        wait_for(lambda: app.player is None)
        (results / 'playlist-gpu-fallback.log').write_text(app.diagnostics)
        print('PASS fallback: MPEG-4 played on CPU and GUI reported it')
    finally:
        app.close()
        if app.player:
            app.player.thread.join(10)
            root.update()
        try:
            root.destroy()
        except tk.TclError:
            pass
