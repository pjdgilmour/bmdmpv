#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Explicit end-to-end GUI test. Opens a window and sends video/audio to hardware."""
from pathlib import Path
import subprocess
import sys
import time
import tkinter as tk
from PIL import Image, ImageGrab

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gui.app import App, messagebox
from gui.core import BASE

results = BASE / 'test-results'
results.mkdir(exist_ok=True)
clip = results / 'gui-4by3.mkv'
if not clip.exists():
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                    '-i', 'testsrc2=size=1440x1080:rate=30000/1001:duration=8',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=8',
                    '-c:v', 'mpeg4', '-q:v', '5', '-af', 'volume=0.05',
                    '-c:a', 'pcm_s16le', '-shortest', str(clip)], check=True)
root = tk.Tk()
errors = []
messagebox.showerror = lambda *args, **kwargs: errors.append(args)
app = App(root, clip)
props = {}
original = app.property_changed

def property_changed(name, value):
    props[name] = value
    original(name, value)
app.property_changed = property_changed

def wait_for(predicate, timeout=20):
    deadline = time.monotonic() + timeout
    while not predicate():
        root.update()
        if errors:
            raise AssertionError((errors, app.diagnostics))
        if time.monotonic() > deadline:
            raise AssertionError((app.status.get(), props, app.diagnostics))
        time.sleep(.02)
    root.update()

def snapshot(name):
    root.update_idletasks()
    x, y = root.winfo_rootx(), root.winfo_rooty()
    ImageGrab.grab((x, y, x + root.winfo_width(), y + root.winfo_height())).save(results / name)

try:
    wait_for(lambda: app.media and app.cards and not app.pending)
    # Exercise the original native-rate path; the YouTube test covers 25→50 Hz.
    app.prefer_high_refresh.set(False)
    app.update_mode()
    assert app.mode.code == 'Hp29', app.mode
    app.volume.set(20)
    app.set_volume(20)
    snapshot('gui-ready.png')
    for ao, target, expected_size, framing in [
            ('decklink', 'Automático · priorizar FPS', (1920, 1080), 0),
            ('pipewire', 'HD · 720p', (1280, 720), 0),
            ('pipewire', 'HD · 720p', (1280, 720), 1),
            ('pipewire', 'HD · 720p', (1280, 720), 2)]:
        props.clear()
        app.audio_combo.current(next(i for i, a in enumerate(app.audio_choices) if a.ao == ao))
        app.target_combo.set(target)
        app.framing_combo.current(framing)
        app.update_mode()
        app.play_button.invoke()
        wait_for(lambda: app.connected and props.get('current-ao') == ao and app.position > .4)
        assert props.get('current-vo') == 'decklink', props
        app.play_button.invoke()
        wait_for(lambda: app.paused)
        before = app.position
        until = time.monotonic() + .3
        wait_for(lambda: time.monotonic() > until)
        assert abs(app.position - before) < .08
        app.seek_scale.set(2)
        app.seek_release()
        wait_for(lambda: abs(app.position - 2) < .08)
        app.delay.set('0.050')
        app.set_delay()
        wait_for(lambda: props.get('audio-delay') == .05)
        app.mute.set(True)
        app.send('set_property', 'mute', True)
        wait_for(lambda: props.get('mute') is True)
        output = results / f'gui-output-{ao}-{framing}.png'
        output.unlink(missing_ok=True)
        app.send('screenshot-to-file', str(output), 'window')
        def image_ready():
            try:
                with Image.open(output) as image:
                    image.verify()
                return True
            except (OSError, SyntaxError):
                return False
        wait_for(image_ready)
        image = Image.open(output).convert('RGB')
        assert image.size == expected_size, image.size
        w, h = image.size
        if framing == 0:
            assert max(image.getpixel((w // 16, h // 2))) <= 3  # 4:3 pillarbox
            assert max(image.getpixel((w * 15 // 16, h // 2))) <= 3
        else:
            assert max(image.getpixel((w // 16, h // 2))) > 30
            assert max(image.getpixel((w * 15 // 16, h // 2))) > 30
        snapshot(f'gui-playing-{ao}-{framing}.png')
        app.play_button.invoke()
        wait_for(lambda: not app.paused and app.position > 2.3)
        if framing == 2:
            app.send('seek', 7.7, 'absolute+exact')
            wait_for(lambda: app.eof)
            assert app.play_button['text'] == 'Reiniciar'
            app.play_button.invoke()
            wait_for(lambda: not app.eof and not app.paused and .1 < app.position < 2)
        app.stop_button.invoke()
        wait_for(lambda: app.player is None)
        (results / f'gui-{ao}-{framing}.log').write_text(app.diagnostics)
        assert 'Displayed ' in app.diagnostics
        assert '[e][vo/decklink]' not in app.diagnostics
        assert '[e][ao/' not in app.diagnostics
        assert not errors, errors
        print(f'PASS GUI: {ao}, {expected_size}, framing={framing}, pause/seek/delay/mute/resume/stop')
    # Closing a running window must release the child and hardware too.
    app.play_button.invoke()
    wait_for(lambda: app.connected and app.position > .4)
    player = app.player
    app.close()
    deadline = time.monotonic() + 12
    while player.thread.is_alive() and time.monotonic() < deadline:
        root.update()
        time.sleep(.02)
    assert not player.thread.is_alive(), 'Owned mpv process not stopped on close'
    print('PASS GUI: close while playing releases mpv')
finally:
    if app.player:
        app.player.stop()
        app.player.thread.join(10)
    try:
        root.destroy()
    except tk.TclError:
        pass
