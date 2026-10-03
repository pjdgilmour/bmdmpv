#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gui.core import Audio, Card, Mode, playback_args, probe_media
from gui.library import Playlist, read_playlist, write_playlist
from gui.sources import normalize_source, youtube_url
from gui.youtube import extract, parse_youtube, ProbeCancelled, extractor_options

URL = 'https://www.youtube.com/watch?v=aqz-KE-bpKQ'
DATA = {'_type': 'video', 'title': 'Vídeo de teste', 'duration': 120, 'width': 3840,
        'height': 2160, 'fps': 60, 'live_status': 'not_live', 'requested_formats': [
            {'format_id': '137', 'width': 1920, 'height': 1080, 'fps': 30,
             'vcodec': 'avc1', 'acodec': 'none', 'dynamic_range': 'SDR', 'url': 'https://cdn.example/temporary-video'},
            {'format_id': '140', 'vcodec': 'none', 'acodec': 'mp4a', 'url': 'https://cdn.example/temporary-audio'}]}


class YouTubeTest(unittest.TestCase):
    def setUp(self):
        p = patch('gui.youtube.find_runtime', return_value='deno:/fixture/deno')
        p.start()
        self.addCleanup(p.stop)

    def test_links_normalization_and_rejected_sources(self):
        for url in [URL + '&list=ignored&t=20', 'https://youtu.be/aqz-KE-bpKQ?si=tracking',
                    'https://m.youtube.com/shorts/aqz-KE-bpKQ', 'https://www.youtube.com/embed/aqz-KE-bpKQ']:
            self.assertEqual(normalize_source(url), URL)
        for url in ['https://youtube.com.evil.test/watch?v=aqz-KE-bpKQ',
                    'https://youtube.com/playlist?list=abc', 'file:///tmp/video',
                    'https://x:secret@youtube.com/watch?v=aqz-KE-bpKQ',
                    'https://youtube.com:123/watch?v=aqz-KE-bpKQ']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                normalize_source(url)

    def test_selected_format_metadata_and_original_url_playback(self):
        media = parse_youtube(URL, DATA)
        self.assertEqual((media.width, media.height, media.fps), (1920, 1080, 30))
        self.assertEqual(media.title, 'Vídeo de teste')
        self.assertTrue(media.audio)
        self.assertIsNone(media.video_id)
        args = playback_args(media, Card(0, 'Intensity'), Mode('Hp30', 1920, 1080, 30, '1080p30'), Audio('HDMI', 'decklink'))
        self.assertIn('--ytdl-format=137+140', args)
        self.assertIn('--ytdl=yes', args)
        self.assertIn('ytdl_hook-all_formats=no', ' '.join(args))
        self.assertEqual(args[-2:], ['--', URL])
        self.assertNotIn('temporary-video', ' '.join(args))
        self.assertFalse(any(arg.startswith('--vid=') for arg in args))

    def test_muxed_video_and_live_hdr_missing_metadata(self):
        muxed = dict(DATA['requested_formats'][0], acodec='aac', duration=3)
        self.assertEqual(parse_youtube(URL, muxed).ytdl_format, '137')
        for change in [{'live_status': 'is_live'}, {'live_status': 'is_upcoming'}, {'_type': 'playlist'}]:
            with self.assertRaises(ValueError):
                parse_youtube(URL, dict(DATA, **change))
        for key, value in [('dynamic_range', 'HDR10'), ('width', 0), ('format_id', '137,best')]:
            bad = copy.deepcopy(DATA)
            bad['requested_formats'][0][key] = value
            with self.assertRaises(ValueError):
                parse_youtube(URL, bad)

    def test_mixed_playlist_roundtrip_retains_source_not_signed_urls(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Playlist([Path(tmp) / 'arquivo com espaço.mp4', 'https://youtu.be/aqz-KE-bpKQ'])
            path = Path(tmp) / 'mixed.m3u8'
            write_playlist(path, p)
            self.assertEqual(read_playlist(path).paths, p.paths)
            self.assertEqual(p.paths[1], URL)
            self.assertIn(URL, path.read_text())

    def test_probe_dispatch_and_missing_extractor(self):
        with patch('gui.youtube.extract', return_value=DATA) as resolve:
            self.assertEqual(probe_media(URL).path, URL)
            resolve.assert_called_once_with(URL, None, browser='', options=extractor_options())
        with patch('gui.youtube.shutil.which', return_value=None), self.assertRaisesRegex(ValueError, 'yt-dlp'):
            extract(URL)

    def test_cancellation_reaps_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / 'yt-dlp'
            pidfile = Path(tmp) / 'pid'
            script.write_text('#!/usr/bin/env python3\nimport os,time\nfrom pathlib import Path\n'
                              f'Path({str(pidfile)!r}).write_text(str(os.getpid()))\ntime.sleep(30)\n')
            script.chmod(0o700)
            cancel = threading.Event()
            caught = []
            def worker():
                try:
                    extract(URL, cancel)
                except Exception as exc:
                    caught.append(exc)
            with patch('gui.youtube.shutil.which', return_value=str(script)):
                thread = threading.Thread(target=worker)
                thread.start()
                try:
                    end = time.monotonic() + 5
                    while not pidfile.exists() and time.monotonic() < end:
                        time.sleep(.01)
                    self.assertTrue(pidfile.exists())
                finally:
                    cancel.set()
                    thread.join(3)
                self.assertFalse(thread.is_alive())
                self.assertIsInstance(caught[0], ProbeCancelled)
                with self.assertRaises(ProcessLookupError):
                    os.kill(int(pidfile.read_text()), 0)

    def test_browser_authentication_reaches_probe_and_player(self):
        with patch('gui.youtube.extract', return_value=DATA) as resolve:
            media = probe_media(URL, browser='firefox')
            resolve.assert_called_once_with(URL, None, browser='firefox', options=extractor_options('firefox'))
        with patch('gui.youtube.find_runtime', side_effect=AssertionError('must reuse probe runtime')):
            args = playback_args(media, Card(0, 'Intensity'), Mode('Hp30', 1920, 1080, 30, '1080p30'), Audio('HDMI', 'decklink'))
        self.assertIn('cookies-from-browser=firefox', ' '.join(args))
        self.assertIn('remote-components=ejs:github', ' '.join(args))
        self.assertIn('js-runtimes=deno:/fixture/deno', ' '.join(args))
        with patch('gui.youtube.find_runtime', return_value='node:/bin/node'):
            self.assertEqual(extractor_options('chrome'), {'cookies-from-browser': 'chrome',
                             'remote-components': 'ejs:github', 'js-runtimes': 'node:/bin/node'})
        self.assertNotIn('cookies-from-browser', extractor_options())
        with self.assertRaises(ValueError):
            extractor_options('firefox,exec=bad')


if __name__ == '__main__':
    unittest.main(verbosity=2)
