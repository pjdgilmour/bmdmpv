#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Native ytdl_hook + separate HTTP streams + IPC, offline fixture, no hardware."""
import argparse
import http.server
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
from functools import partial
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gui.core import MPV, Audio, Card, Mode, Player, playback_args, probe_media

parser = argparse.ArgumentParser()
parser.add_argument('--with-cookies', action='store_true', help='Use simulated browser cookies; never reads a browser.')
options = parser.parse_args()
browser = 'firefox' if options.with_cookies else ''

with tempfile.TemporaryDirectory() as tmp:
    directory = Path(tmp)
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                    '-i', 'testsrc2=size=640x360:rate=30:duration=4', '-an', '-c:v', 'libx264',
                    '-preset', 'ultrafast', str(directory / 'video.mp4')], check=True)
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                    '-i', 'anullsrc=r=48000:cl=stereo', '-t', '4', '-c:a', 'aac',
                    str(directory / 'audio.m4a')], check=True)
    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=tmp))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    prefix = f'http://127.0.0.1:{server.server_port}/'
    for lang in ('en', 'pt'):
        (directory / (lang + '.srt')).write_text('1\n00:00:00,000 --> 00:00:04,000\nSubtitle ' + lang + '\n')
    data = {'_type': 'video', 'title': 'YouTube integration fixture', 'duration': 4,
            'requested_subtitles': {lang: {'ext': 'srt', 'url': prefix + lang + '.srt'} for lang in ('en', 'pt')},
            'requested_formats': [
                {'format_id': '137', 'width': 640, 'height': 360, 'fps': 30,
                 'vcodec': 'h264', 'acodec': 'none', 'dynamic_range': 'SDR',
                 'protocol': 'http', 'url': prefix + 'video.mp4'},
                {'format_id': '140', 'vcodec': 'none', 'acodec': 'aac',
                 'protocol': 'http', 'url': prefix + 'audio.m4a'}]}
    fake = directory / 'yt-dlp'
    runtime = 'deno:/fixture/espaço, com vírgula/deno'
    check = ("assert '--js-runtimes' in sys.argv\n"
             "assert sys.argv[sys.argv.index('--js-runtimes') + 1] == " + repr(runtime) + '\n'
             "if '--write-srt' in sys.argv: assert sys.argv[sys.argv.index('--sub-langs') + 1] == 'all'\n")
    if browser:
        for fmt in data['requested_formats']:
            fmt['cookies'] = 'fixture=FAKE_COOKIE_MUST_NOT_BE_LOGGED; Domain=127.0.0.1; Path=/'
        check += ("assert '--cookies-from-browser' in sys.argv\n"
                 "assert sys.argv[sys.argv.index('--cookies-from-browser') + 1] == 'firefox'\n"
                 "assert '--remote-components' in sys.argv\n")
    fake.write_text('#!/usr/bin/env python3\nimport sys\n' + check + 'print(' + repr(json.dumps(data)) + ')\n')
    fake.chmod(0o700)
    events = queue.Queue()
    player = None
    properties = {}
    def wait(predicate):
        end = time.monotonic() + 12
        while time.monotonic() < end:
            source, kind, value = events.get(timeout=max(.1, end - time.monotonic()))
            if kind == 'finished' and value['error']:
                raise AssertionError(value)
            if kind == 'command-error':
                raise AssertionError(value)
            if kind == 'property':
                properties[value[0]] = value[1]
            if predicate(kind, value):
                return value
        raise AssertionError('IPC timeout')
    try:
        with patch.dict(os.environ, PATH=tmp + os.pathsep + os.environ.get('PATH', '')), \
                patch('gui.youtube.find_runtime', return_value=runtime):
            media = probe_media('https://youtu.be/aqz-KE-bpKQ', browser=browser)
            args = playback_args(media, Card(0, 'fixture'), Mode('Hp30', 1920, 1080, 30, '1080p30'), Audio('fixture', 'decklink'))
            args = [a.replace('--vo=decklink', '--vo=null').replace('--ao=decklink', '--ao=null') for a in args]
            args.insert(1, '--pause=yes')
            player = Player(args, events)
            player.start()
            seen = set()
            def ready(kind, value):
                if kind == 'property' and value in (('current-vo', 'null'), ('current-ao', 'null')):
                    seen.add(value[0])
                return len(seen) == 2
            wait(ready)
            assert len([t for t in properties['track-list'] if t['type'] == 'sub']) == 2
            player.command('set_property', 'sid', 2)
            wait(lambda k, v: k == 'property' and v == ('sid', 2))
            player.command('set_property', 'sid', False)
            wait(lambda k, v: k == 'property' and v == ('sid', False))
            player.command('seek', 1.5, 'absolute+exact')
            wait(lambda k, v: k == 'property' and v[0] == 'time-pos' and abs((v[1] or 0) - 1.5) < .1)
            player.command('set_property', 'pause', False)
            wait(lambda k, v: k == 'property' and v[0] == 'time-pos' and (v[1] or 0) > 1.7)
            player.stop()
            result = wait(lambda k, v: k == 'finished')
            assert result['code'] == 0 and not result['error'], result
            if browser:
                assert 'FAKE_COOKIE_MUST_NOT_BE_LOGGED' not in result['log']
            else:
                assert 'youtube-dl succeeded' in result['log']
            print('PASS: native Lua ytdl hook, HTTP video/audio/subtitles, subtitle selection, pause/seek/resume/stop with null outputs')
    finally:
        if player:
            player.stop()
            player.thread.join(10)
        server.shutdown()
        server.server_close()
        thread.join(2)
