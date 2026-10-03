#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gui.library import Playlist, ProfileStore, read_playlist, write_playlist

PROFILE = dict(card_index=0, card_name='Intensity Pro 4K', target='auto', mode='Hp29',
               audio_ao='pipewire', audio_device='auto', framing='fit', volume=23.5,
               mute=False, delay=-.025, repeat='playlist', hwdec='nvdec-copy')


class PlaylistTest(unittest.TestCase):
    def test_reorder_remove_and_wrap_keep_current_item(self):
        p = Playlist(['/a', '/b', '/c', '/b'])
        p.index = 2
        p.move(0, 2)
        self.assertEqual(p.paths[p.index], '/c')
        self.assertEqual(p.index, 1)
        p.move(1, -1)
        self.assertEqual(p.index, 0)
        self.assertIsNone(p.adjacent(-1))
        self.assertEqual(p.adjacent(-1, True), 3)
        p.remove(0)
        self.assertEqual(p.index, 0)
        p.index = 2
        p.remove(0)
        self.assertEqual(p.index, 1)
        p.remove(1)
        p.remove(0)
        self.assertEqual(p.index, -1)
        self.assertIsNone(p.adjacent(1, True))
        p.append(['/new'])
        self.assertEqual(p.index, 0)

    def test_m3u8_roundtrip_relative_paths_comments_unicode_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'lista.m3u8'
            path.write_text('\ufeff#EXTM3U\n#EXTINF:4,Teste\nvídeo com espaço.mkv\nsub/outro.mp4\nvídeo com espaço.mkv\n', encoding='utf-8')
            p = read_playlist(path)
            self.assertEqual(p.paths, [str(Path(tmp) / f) for f in ['vídeo com espaço.mkv', 'sub/outro.mp4', 'vídeo com espaço.mkv']])
            p.append([Path(tmp) / 'ends with space '])
            write_playlist(path, p)
            self.assertEqual(read_playlist(path).paths, p.paths)
            path.write_text('https://example.com/movie.mp4\n')
            with self.assertRaises(ValueError):
                read_playlist(path)


class ProfilesTest(unittest.TestCase):
    def test_persistence_update_delete_and_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'nested/profiles.json'
            a, b = ProfileStore(path), ProfileStore(path)
            a.save(' HDMI cinema ', PROFILE)
            b.save('Yamaha', dict(PROFILE, target='manual', audio_device='pipewire/yamaha'))
            a.save('HDMI cinema', dict(PROFILE, volume=42))
            data = ProfileStore(path).read()
            self.assertEqual(set(data), {'HDMI cinema', 'Yamaha'})
            self.assertEqual(data['HDMI cinema']['volume'], 42)
            self.assertEqual(data['Yamaha']['audio_device'], 'pipewire/yamaha')
            a.delete('HDMI cinema')
            self.assertEqual(list(b.read()), ['Yamaha'])

    def test_bad_config_and_failed_write_preserve_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'profiles.json'
            store = ProfileStore(path)
            for malformed in ('{incomplete', '{"version":2,"profiles":{}}',
                              '{"version":1,"profiles":{"bad":{}}}'):
                path.write_text(malformed)
                with self.assertRaises(ValueError):
                    store.save('new', PROFILE)
                self.assertEqual(path.read_text(), malformed)
            path.unlink()
            store.save('original', PROFILE)
            original = path.read_text()
            with patch('gui.library.os.replace', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    store.save('new', PROFILE)
            self.assertEqual(path.read_text(), original)
            self.assertEqual(list(Path(tmp).iterdir()), [path])

    def test_validation_does_not_clobber_saved_profiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ProfileStore(Path(tmp) / 'profiles.json')
            store.save('valid', PROFILE)
            for key, value in [('hwdec', 'nvdec'), ('volume', float('nan')), ('delay', 30),
                               ('mute', 'yes'), ('repeat', 'anything'), ('card_index', -1)]:
                with self.subTest(key=key), self.assertRaises(ValueError):
                    store.save('bad', dict(PROFILE, **{key: value}))
            self.assertEqual(store.read(), {'valid': PROFILE})


if __name__ == '__main__':
    unittest.main(verbosity=2)
