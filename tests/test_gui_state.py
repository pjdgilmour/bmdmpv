#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Tk controller tests with simulated devices/player; needs DISPLAY, no hardware."""
from pathlib import Path
import sys
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gui.app import App
from gui.core import Audio, Card, Media, Mode
from gui.library import Playlist, ProfileStore


class FakePlayer:
    def __init__(self, args, events):
        self.args, self.events = args, events
        self.stopping = threading.Event()
        self.commands = []

    def emit(self, kind, value):
        self.events.put((self, kind, value))

    def start(self):
        self.emit('connected', None)
        self.emit('property', ('pause', False))

    def stop(self):
        if not self.stopping.is_set():
            self.stopping.set()
            self.emit('finished', dict(code=0, error=None, log='mock playback done'))

    def command(self, *args):
        self.commands.append(args)


def probe(path):
    if path.endswith('missing.mkv'):
        raise ValueError('Arquivo não encontrado')
    return Media(path, 1280, 720, 50 if path.endswith('b.mkv') else 30000/1001,
                 2, True, True, unsupported_color=path.endswith('hdr.mkv'))


class ControllerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [patch('gui.app.Player', FakePlayer), patch('gui.app.probe_media', probe),
                        patch('gui.app.discover_cards', lambda: [Card(0, 'Intensity', [
                            Mode('Hp29', 1920, 1080, 30000/1001, '1080p29.97'),
                            Mode('hp50', 1280, 720, 50, '720p50')])]),
                        patch('gui.app.discover_audio', lambda: [Audio('HDMI', 'decklink'), Audio('Yamaha', 'pipewire', 'pipewire/yamaha')]),
                        patch('gui.app.messagebox.showerror')]
        for p in self.patches:
            p.start()
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = App(self.root, profile_path=Path(self.tmp.name) / 'profiles.json')
        self.wait(lambda: not self.app.pending)

    def tearDown(self):
        self.app.close()
        if self.app.player:
            self.wait(lambda: self.app.player is None)
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def wait(self, predicate):
        deadline = time.monotonic() + 4
        while not predicate():
            self.root.update()
            if time.monotonic() > deadline:
                self.fail(self.app.status.get())
            time.sleep(.005)
        self.root.update()

    def start_playlist(self, paths=('/a.mkv', '/b.mkv')):
        self.app.add_files(paths)
        self.wait(lambda: self.app.media is not None)
        self.app.play_pause()
        self.wait(lambda: self.app.connected)
        return self.app.player

    def test_eof_recalculates_mode_and_stops_at_last_item(self):
        first = self.start_playlist()
        self.assertEqual(self.app.mode.code, 'Hp29')
        first.emit('property', ('eof-reached', True))
        self.wait(lambda: self.app.player is not None and self.app.player is not first and self.app.connected)
        second = self.app.player
        self.assertEqual(self.app.playlist.index, 1)
        self.assertEqual(self.app.mode.code, 'hp50')
        second.emit('property', ('eof-reached', True))
        self.wait(lambda: self.app.eof)
        self.assertIs(self.app.player, second)
        self.assertEqual(self.app.play_button['text'], 'Reiniciar')

    def test_repeat_playlist_and_repeat_file(self):
        first = self.start_playlist()
        self.app.repeat_combo.set('Repetir playlist')
        self.app.repeat_changed()
        self.app.next_item()
        self.wait(lambda: self.app.connected and self.app.player is not first)
        second = self.app.player
        second.emit('property', ('eof-reached', True))
        self.wait(lambda: self.app.connected and self.app.player is not second)
        self.assertEqual(self.app.playlist.index, 0)
        self.app.repeat_combo.set('Repetir arquivo')
        self.app.repeat_changed()
        self.assertEqual(self.app.player.commands[-1], ('set_property', 'loop-file', 'inf'))

    def test_stop_during_transition_does_not_restart(self):
        self.start_playlist()
        self.app.next_item()
        self.app.stop()
        self.wait(lambda: self.app.player is None and self.app.media is not None and not self.app.pending)
        self.assertEqual(self.app.playlist.index, 1)
        self.assertFalse(self.app.busy())
        self.assertTrue(self.app.media.path.endswith('b.mkv'))

    def test_stop_during_probe_and_ignore_stale_result(self):
        self.app.replace_playlist(Playlist(['/a.mkv', '/b.mkv']))
        self.wait(lambda: self.app.media is not None)
        gate = threading.Event()
        original = probe
        def delayed(path):
            gate.wait(3)
            return original(path)
        with patch('gui.app.probe_media', delayed):
            self.app.select_item(1, autoplay=True)
            self.app.stop()
        gate.set()
        self.wait(lambda: not self.app.pending)
        self.assertIsNone(self.app.player)
        self.assertTrue(self.app.media.path.endswith('b.mkv'))
        self.app.select_item(0)
        stale = self.app.generation
        self.app.select_item(1)
        self.app.events.put((('media', stale), 'result', probe('/a.mkv')))
        self.wait(lambda: not self.app.pending)
        self.assertTrue(self.app.media.path.endswith('b.mkv'))

    def test_bad_item_stops_playlist_instead_of_skipping_or_looping(self):
        for path in ('/missing.mkv', '/hdr.mkv'):
            self.app.replace_playlist(Playlist(['/a.mkv', path]))
            self.wait(lambda: self.app.media is not None)
            self.app.play_pause()
            self.wait(lambda: self.app.connected)
            self.app.player.emit('property', ('eof-reached', True))
            self.wait(lambda: self.app.playlist.index == 1 and not self.app.busy() and not self.app.pending)
            self.assertIsNone(self.app.player)

    def test_profile_roundtrip_and_missing_audio_are_atomic(self):
        self.app.add_files(['/a.mkv'])
        self.wait(lambda: self.app.media is not None)
        self.app.audio_combo.current(1)
        self.app.decoder_combo.set('NVIDIA · NVDEC')
        self.app.volume.set(32)
        self.app.repeat_combo.set('Repetir playlist')
        data = self.app.profiles.snapshot()
        self.app.profile_store.save('Yamaha GPU', data)
        restored = ProfileStore(self.app.profile_store.path).read()['Yamaha GPU']
        self.app.audio_combo.current(0)
        self.app.volume.set(80)
        self.app.profiles.apply_data(restored)
        self.assertEqual(self.app.profiles.snapshot(), data)
        before = self.app.profiles.snapshot()
        with self.assertRaises(ValueError):
            self.app.profiles.apply_data(dict(restored, audio_device='pipewire/unplugged', volume=99))
        self.assertEqual(self.app.profiles.snapshot(), before)
        self.app.show_playlist()
        self.app.playlist_window.tree.selection_set('0')
        self.app.playlist_window.remove()
        self.assertIsNone(self.app.media)
        self.assertEqual(self.app.playlist.index, -1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
