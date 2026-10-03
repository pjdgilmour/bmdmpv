#!/usr/bin/env python3
"""Explicit HDMI A/V test; generates low-level tones and requires the device."""
import json
from pathlib import Path
import re
import socket
import subprocess
import tempfile
import time

base = Path(__file__).resolve().parent.parent
results = base / 'test-results'
results.mkdir(exist_ok=True)
clip = results / 'av-multitrack.mkv'
if not clip.exists():
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error',
        '-f', 'lavfi', '-i', 'testsrc2=size=1280x720:rate=30000/1001:duration=14',
        '-f', 'lavfi', '-i', 'aevalsrc=0.03*sin(2*PI*440*t)|0.03*sin(2*PI*660*t):s=44100:d=14',
        '-f', 'lavfi', '-i', 'aevalsrc=0.03*sin(2*PI*330*t):s=32000:d=14',
        '-f', 'lavfi', '-i', 'aevalsrc=0.02*sin(2*PI*220*t)|0|0.02*sin(2*PI*440*t)|0|0|0:s=96000:d=14:c=5.1',
        '-map', '0:v', '-map', '1:a', '-map', '2:a', '-map', '3:a',
        '-c:v', 'mpeg4', '-q:v', '3', '-c:a', 'pcm_s16le', str(clip)], check=True)

with tempfile.TemporaryDirectory(prefix='bmd-audio-', dir='/tmp') as tmp:
    ipc = str(Path(tmp)/'ipc')
    log = results/'audio-hardware.log'
    proc = subprocess.Popen([str(base/'mpv-decklink'), '--vo-decklink-mode=Hp29',
        '--no-terminal', '--input-ipc-server='+ipc, '--log-file='+str(log),
        '--pause', str(clip)])
    sock = socket.socket(socket.AF_UNIX)
    try:
        deadline = time.monotonic() + 15
        while not Path(ipc).exists():
            assert proc.poll() is None, log.read_text()
            assert time.monotonic() < deadline
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
                reply = json.loads(stream.readline())
                if reply.get('request_id') == request_id:
                    assert reply['error'] == 'success', reply
                    return reply.get('data')

        def get(name):
            return command('get_property', name)

        def wait_for(predicate):
            deadline = time.monotonic() + 10
            while True:
                try:
                    if predicate():
                        return
                except (AssertionError, TypeError):
                    assert proc.poll() is None, log.read_text()
                assert time.monotonic() < deadline, log.read_text()[-3000:]
                time.sleep(.05)

        wait_for(lambda: get('current-ao') == 'decklink')
        # Starting paused must not submit audio before start().
        assert get('pause')
        command('set_property', 'pause', False)
        wait_for(lambda: get('audio-pts') > .7)
        assert get('current-vo') == 'decklink'
        params = get('audio-out-params')
        assert params['samplerate'] == 48000 and params['channel-count'] == 2, params
        avsync = []
        for _ in range(8):
            avsync.append(get('avsync'))
            time.sleep(.15)
        assert max(abs(x) for x in avsync) < .1, avsync
        command('set_property', 'pause', True)
        time.sleep(.2)
        paused = get('audio-pts')
        time.sleep(.3)
        assert abs(get('audio-pts')-paused) < .01
        command('set_property', 'pause', False)
        wait_for(lambda: get('audio-pts') > paused + .3)
        command('set_property', 'pause', True)
        command('seek', 5, 'absolute+exact')
        time.sleep(.3)
        command('set_property', 'pause', False)
        wait_for(lambda: 5 < get('audio-pts') < 6)
        for aid, rate, channels in [(2, 32000, 1), (3, 96000, 6), (1, 44100, 2)]:
            command('set_property', 'aid', aid)
            wait_for(lambda: get('audio-params')['samplerate'] == rate)
            assert get('audio-params')['channel-count'] == channels
            params = get('audio-out-params')
            assert params['samplerate'] == 48000 and params['channel-count'] == 2
            time.sleep(.4)
        command('set_property', 'mute', True)
        assert get('mute')
        command('set_property', 'volume', 25)
        assert get('volume') == 25
        command('set_property', 'mute', False)
        # Drain to EOF naturally; covers tail playback and shared teardown.
        command('seek', 12, 'absolute+exact')
        assert proc.wait(timeout=10) == 0
        text = log.read_text()
        assert not re.search(r'\[e\]\[(?:ao|vo)/decklink\]', text), text[-4000:]
        counts = re.findall(r'Submitted (\d+) audio sample frames', text)
        assert counts and sum(map(int, counts)) > 48000, counts
        print('PASS HDMI audio: start paused, 44.1/32/96 kHz, stereo/mono/5.1 downmix, '
              'pause/resume, seek, track changes, volume/mute and EOF')
        print(f'mpv-reported A/V difference: {min(avsync):.4f} to {max(avsync):.4f} s '
              '(not a measurement of the physical HDMI signal)')
    finally:
        sock.close()
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

# The AO can survive across playlist entries; test synchronous-engine reuse
# after a drained queue, not only closing and reopening the whole player.
playlist_log = results/'audio-playlist.log'
subprocess.run([str(base/'mpv-decklink'), '--vo-decklink-mode=Hp29',
    '--length=2', '--no-terminal', '--log-file='+str(playlist_log),
    str(clip), str(clip)], check=True, timeout=15)
text = playlist_log.read_text()
assert not re.search(r'\[e\]\[(?:ao|vo)/decklink\]', text), text[-4000:]
assert text.count('finished playback, success') == 2
print('PASS HDMI audio: drain and restart across two playlist entries')
