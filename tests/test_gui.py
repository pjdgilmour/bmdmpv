#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""GUI logic and real mpv IPC tests without display, card, or sound output."""
import json
from pathlib import Path
import queue
import sys
import tempfile
import time
import unittest
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gui.core import (Audio, Card, Media, Mode, MPV, Player, choose_mode, mode_note,
                      parse_audio, parse_cards, parse_media, playback_args)

MODES = [Mode(code, w, h, fps, code) for code, w, h, fps in [
    ('23ps', 1920, 1080, 24000/1001), ('24ps', 1920, 1080, 24),
    ('Hp25', 1920, 1080, 25), ('Hp29', 1920, 1080, 30000/1001),
    ('Hp30', 1920, 1080, 30), ('Hp50', 1920, 1080, 50),
    ('Hp59', 1920, 1080, 60000/1001), ('Hp60', 1920, 1080, 60),
    ('hp50', 1280, 720, 50), ('hp59', 1280, 720, 60000/1001),
    ('hp60', 1280, 720, 60), ('4k23', 3840, 2160, 24000/1001),
    ('4k24', 3840, 2160, 24), ('4k29', 3840, 2160, 30000/1001),
    ('4k30', 3840, 2160, 30)]]


def media(w=1920, h=1080, fps=24):
    return Media('/tmp/arquivo com espaços; $(false).mkv', w, h, fps, 10, True, True)


class ModesTest(unittest.TestCase):
    def test_hdmi_high_refresh_keeps_resolution_and_even_cadence(self):
        for fps, expected in [(25, 'Hp50'), (30000/1001, 'Hp59'), (30, 'Hp60'),
                              (24, '24ps'), (24000/1001, '23ps'), (50, 'Hp50')]:
            with self.subTest(fps=fps):
                self.assertEqual(choose_mode(MODES, media(fps=fps), prefer_high_refresh=True).code, expected)
        self.assertEqual(choose_mode(MODES, media(fps=25)).code, 'Hp25')
        self.assertEqual(choose_mode(MODES, media(3840, 2160, 30), prefer_high_refresh=True).code, '4k30')
        note = mode_note(choose_mode(MODES, media(fps=25), prefer_high_refresh=True), media(fps=25))
        self.assertIn('quadros repetidos 2×', note)

    def test_fps_and_geometry(self):
        for w, h, fps, code in [(1920, 800, 24000/1001, '23ps'),
                               (1920, 1080, 24, '24ps'),
                               (1280, 720, 30000/1001, 'Hp29'),
                               (3840, 2160, 60, 'Hp60'),
                               (3840, 2160, 30000/1001, '4k29'),
                               (1280, 720, 60000/1001, 'hp59')]:
            with self.subTest(code=code):
                self.assertEqual(choose_mode(MODES, media(w, h, fps)).code, code)

    def test_forced_resolution_and_warning(self):
        source = media(3840, 2160, 24)
        self.assertEqual(choose_mode(MODES, source, 1080).code, '24ps')
        mode = choose_mode(MODES, source, 720)
        self.assertEqual(mode.height, 720)
        self.assertIn('Cadência adaptada', mode_note(mode, source))
        with self.assertRaises(ValueError):
            choose_mode(MODES, source, 480)
        self.assertEqual(choose_mode(MODES, media(fps=0)).code, 'Hp30')

    def test_card_discovery_preserves_case_and_indices(self):
        cards = parse_cards('Device 0: Capture\nDevice 2: Intensity\n  Hp59  1920x1080  59.940060 fps  1080p59.94\n  hp59  1280x720  59.940060 fps  720p59.94\n')
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].index, 2)
        self.assertEqual([m.code for m in cards[0].modes], ['Hp59', 'hp59'])

    def test_audio_discovery(self):
        choices = parse_audio("  'auto' (Autoselect device)\n  'pipewire/foo' (AG06 (USB))\n  'pulse/foo' (AG06)\n", 'pipewire pulse decklink')
        self.assertEqual(choices[1].device, 'auto')
        self.assertEqual(choices[3].device, 'pipewire/foo')
        self.assertIn('AG06 (USB)', choices[3].label)
        self.assertEqual(choices[-1].ao, 'none')

    def test_metadata_rotation_sar_hdr_and_attached_picture(self):
        streams = [{'codec_type': 'video', 'disposition': {'attached_pic': 1}},
                   {'codec_type': 'audio'},
                   {'codec_type': 'video', 'width': 1440, 'height': 1080,
                    'sample_aspect_ratio': '4:3', 'avg_frame_rate': '0/0',
                    'r_frame_rate': '25/1', 'field_order': 'tt',
                    'side_data_list': [{'rotation': -90}], 'color_transfer': 'smpte2084'}]
        result = parse_media('test.mkv', {'streams': streams})
        self.assertEqual((result.width, result.height), (1080, 1920))
        self.assertEqual(result.fps, 50)
        self.assertEqual(result.video_id, 2)
        self.assertTrue(result.unsupported_color)
        self.assertTrue(result.audio)

    def test_command_routing_and_literal_filename(self):
        source = media()
        source.video_id = 1
        for ao in ('decklink', 'pipewire', 'pulse', 'none'):
            args = playback_args(source, Card(2, 'Test'), MODES[1], Audio('Test', ao), 'fill', 25, .1, True)
            self.assertEqual(args[-2:], ['--', source.path])
            self.assertIn('--vo=decklink', args)
            self.assertIn('--panscan=1', args)
            self.assertIn('--vid=1', args)
            self.assertIn('--audio=no' if ao == 'none' else '--ao=' + ao, args)
            self.assertIn('--loop-file=inf', args)
        source.unsupported_color = True
        with self.assertRaises(ValueError):
            playback_args(source, Card(0, 'Test'), MODES[0], Audio('HDMI', 'decklink'))
        source.unsupported_color = False
        with self.assertRaises(ValueError):
            playback_args(source, Card(0, 'Test'), MODES[0], Audio('HDMI', 'decklink'), delay=float('nan'))

    def test_gpu_options_require_copy_back(self):
        for hwdec in ('no', 'auto-copy', 'nvdec-copy', 'vaapi-copy'):
            args = playback_args(media(), Card(0, 'Test'), MODES[0], Audio('HDMI', 'decklink'), hwdec=hwdec)
            self.assertIn('--hwdec=' + hwdec, args)
        with self.assertRaises(ValueError):
            playback_args(media(), Card(0, 'Test'), MODES[0], Audio('HDMI', 'decklink'), hwdec='nvdec')


@unittest.skipUnless(MPV.exists(), 'Compile o mpv local para testar IPC.')
class IPCTest(unittest.TestCase):
    def wait_for(self, predicate, timeout=12):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                event = self.events.get(timeout=max(.1, end - time.monotonic()))
            except queue.Empty:
                self.fail(str(self.seen))
            self.seen.append(event)
            if predicate(event):
                return event[2]
            if event[1] == 'finished':
                self.fail(str(event[2]))
        self.fail(str(self.seen))

    def test_real_mpv_pause_seek_volume_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'clip com espaços.wav'
            with wave.open(str(path), 'wb') as f:
                f.setparams((2, 2, 48000, 0, 'NONE', 'not compressed'))
                f.writeframes(b'\0' * (48000 * 4 * 5))
            self.events, self.seen = queue.Queue(), []
            source = Media(str(path), 0, 0, 0, 5, True, False)
            args = playback_args(source, Card(0, 'Test'), MODES[0], Audio('Test', 'decklink'))
            args = [a.replace('--vo=decklink', '--vo=null').replace('--ao=decklink', '--ao=null') for a in args]
            args.insert(1, '--pause=yes')
            player = Player(args, self.events)
            player.start()
            try:
                self.wait_for(lambda e: e[1] == 'property' and e[2] == ('pause', True))
                player.command('set_property', 'pause', False)
                self.wait_for(lambda e: e[1] == 'property' and e[2][0] == 'time-pos' and (e[2][1] or 0) > .1)
                player.command('set_property', 'pause', True)
                self.wait_for(lambda e: e[1] == 'property' and e[2] == ('pause', True))
                player.command('seek', 2, 'absolute+exact')
                self.wait_for(lambda e: e[1] == 'property' and e[2][0] == 'time-pos' and abs((e[2][1] or 0) - 2) < .05)
                player.command('set_property', 'volume', 17)
                self.wait_for(lambda e: e[1] == 'property' and e[2] == ('volume', 17))
            finally:
                player.stop()
                player.thread.join(10)
            self.assertFalse(player.thread.is_alive())
            finished = self.wait_for(lambda e: e[1] == 'finished')
            self.assertEqual(finished['code'], 0, finished)
            self.assertIsNone(finished['error'], finished)
            self.assertFalse(any(e[1] == 'command-error' for e in self.seen), self.seen)

    def test_start_failure_and_immediate_stop(self):
        for executable in ('/nonexistent/bmdmpv', str(MPV)):
            self.events, self.seen = queue.Queue(), []
            player = Player([executable, '--no-config', '--idle=yes', '--vo=null', '--ao=null', '--'], self.events)
            if executable == str(MPV):
                player.stop()
            player.start()
            finished = self.wait_for(lambda e: e[1] == 'finished')
            player.thread.join(1)
            self.assertFalse(player.thread.is_alive())
            if executable.startswith('/nonexistent'):
                self.assertIsNotNone(finished['error'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
