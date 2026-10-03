#!/usr/bin/env python3
"""Explicit hardware test: sends a short pattern to HDMI; never run by Meson."""
import argparse
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import time

parser = argparse.ArgumentParser()
parser.add_argument('--mode', default='Hp29', choices=['Hp29', '4k29'])
args = parser.parse_args()
base = Path(__file__).resolve().parent.parent
results = base / 'test-results'
results.mkdir(exist_ok=True)
clip = results / 'pattern.mkv'
if not clip.exists():
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                    '-i', 'testsrc2=size=1280x720:rate=30000/1001:duration=5',
                    '-c:v', 'mpeg4', '-q:v', '3', str(clip)], check=True)

with tempfile.TemporaryDirectory(prefix='bmdmpv-', dir='/tmp') as tmp:
    ipc = str(Path(tmp) / 'ipc')
    log_path = results / f'hardware-{args.mode}.log'
    with (results / f'hardware-{args.mode}-console.log').open('w') as log:
        proc = subprocess.Popen([str(base/'mpv-decklink'), '--loop-file=inf',
            '--no-terminal', '--log-file='+str(log_path), '--vo-decklink-mode='+args.mode,
            '--vf=lavfi=[scale=640:480,setsar=1]', '--osd-align-x=center',
            '--osd-align-y=center', '--input-ipc-server='+ipc, str(clip)],
            stdout=log, stderr=log)
        sock = socket.socket(socket.AF_UNIX)
        try:
            deadline = time.monotonic() + 15
            while not Path(ipc).exists():
                assert proc.poll() is None, log_path.read_text()
                assert time.monotonic() < deadline, 'IPC timeout'
                time.sleep(.05)
            sock.connect(ipc)
            sock.settimeout(10)
            stream = sock.makefile('r')
            request_id = 0

            def command(*cmd):
                global request_id
                request_id += 1
                sock.sendall((json.dumps({'command': cmd, 'request_id': request_id})+'\n').encode())
                while True:
                    line = stream.readline()
                    assert line, log_path.read_text()
                    reply = json.loads(line)
                    if reply.get('request_id') == request_id:
                        assert reply['error'] == 'success', reply
                        return reply.get('data')

            while True:
                try:
                    if command('get_property', 'time-pos') > .4:
                        break
                except (AssertionError, TypeError):
                    assert proc.poll() is None, log_path.read_text()
                assert time.monotonic() < deadline, 'Playback did not start'
                time.sleep(.05)
            assert command('get_property', 'current-vo') == 'decklink'
            assert abs(command('get_property', 'display-fps') - 30000/1001) < .00001
            command('set_property', 'pause', True)
            time.sleep(.15)
            paused = command('get_property', 'time-pos')
            time.sleep(.2)
            assert abs(command('get_property', 'time-pos') - paused) < .05
            command('seek', 2, 'absolute+exact')
            time.sleep(.3)
            assert abs(command('get_property', 'time-pos') - 2) < .08
            command('show-text', 'DeckLink HDMI - teste de OSD', 2000)
            time.sleep(.2)
            screenshot = results / f'hardware-{args.mode}.png'
            command('screenshot-to-file', str(screenshot), 'window')
            from PIL import Image
            image = Image.open(screenshot).convert('RGB')
            width, height = (1920, 1080) if args.mode == 'Hp29' else (3840, 2160)
            assert image.size == (width, height)
            # A 4:3 image in 16:9 must have black side bars and visible content.
            assert max(image.getpixel((width//16, height//2))) <= 3
            assert max(image.getpixel((width*15//16, height//2))) <= 3
            assert image.crop((width//4, height//4, width*3//4, height*3//4)).getextrema() != ((0,0),)*3
            command('set_property', 'pause', False)
            time.sleep(.5)
            assert command('get_property', 'time-pos') > 2.2
            command('quit')
            assert proc.wait(timeout=10) == 0
        finally:
            sock.close()
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=10)
    text = log_path.read_text()
    assert '[e][vo/decklink]' not in text, text
    assert 'HDMI device 0:' in text and 'Displayed ' in text, text
    print(f'PASS {args.mode}: HDMI output, fractional fps, aspect ratio, pause, seek, screenshot/OSD, resume and close')
