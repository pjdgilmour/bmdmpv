#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Smoke-test the extracted package; no installation, display or card required."""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile

BASE = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('package', nargs='?', type=Path, default=BASE / 'dist/bmdmpv_0.1.2-1_amd64.deb')
parser.add_argument('--gui', action='store_true', help='Also initialize the installed Tk GUI (requires DISPLAY).')
args = parser.parse_args()
env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
env.pop('LD_LIBRARY_PATH', None)


def run(command):
    return subprocess.check_output([str(a) for a in command], text=True, env=env,
                                   stderr=subprocess.STDOUT, timeout=30)


with tempfile.TemporaryDirectory(prefix='bmdmpv-deb-test-') as tmp:
    root = Path(tmp)
    run(['dpkg-deb', '--extract', args.package, root])
    run(['dpkg-deb', '--control', args.package, root / 'control'])
    private = root / 'usr/lib/bmdmpv'
    metadata = run(['dpkg-deb', '--field', args.package])
    assert 'Architecture: amd64' in metadata
    assert 'desktopvideo (>= 16.0)' in metadata
    assert not (root / 'usr/bin/mpv').exists(), 'Must not replace system mpv'
    for line in (root / 'control/md5sums').read_text().splitlines():
        digest, name = line.split('  ', 1)
        assert hashlib.md5((root / name).read_bytes()).hexdigest() == digest, name
    for name in ('bmdmpv-gui', 'mpv-decklink'):
        assert (root / 'usr/bin' / name).resolve() == private / name
    assert 'YouTube' in run([root / 'usr/bin/bmdmpv-gui', '--help'])
    assert 'decklink' in run([root / 'usr/bin/mpv-decklink', '--vo=help'])
    assert 'decklink' in run([root / 'usr/bin/mpv-decklink', '--ao=help'])
    deps = run(['ldd', private / 'mpv'])
    assert 'not found' not in deps, deps
    assert str(private / 'lib/libplacebo.so.374') in deps, deps
    assert str(BASE / '.deps') not in deps, deps
    dynamic = run(['readelf', '-d', private / 'mpv'])
    assert '[$ORIGIN/lib]' in dynamic
    code = ('import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); '
            'from gui.core import MPV, PROBE; '
            'assert MPV == Path(sys.argv[1]) / "mpv"; '
            'assert PROBE == Path(sys.argv[1]) / "decklink-probe"')
    run(['python3', '-c', code, private])
    if args.gui:
        gui_code = '''
import sys, time, tkinter as tk
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
from gui.app import App
from gui.core import Audio, Card, Mode
with patch('gui.app.discover_cards', return_value=[Card(0, 'Fixture', [Mode('Hp50', 1920, 1080, 50, '1080p50')])]), \\
     patch('gui.app.discover_audio', return_value=[Audio('HDMI', 'decklink')]):
    root = tk.Tk()
    root.withdraw()
    app = App(root, profile_path=Path(sys.argv[2]) / 'profiles.json')
    try:
        end = time.monotonic() + 5
        while app.pending and time.monotonic() < end:
            root.update()
            time.sleep(.01)
        assert not app.pending and app.cards
        assert app.prefer_high_refresh.get()
        assert app.browser_combo.get() == 'Sem cookies'
    finally:
        app.close()
'''
        run(['python3', '-c', gui_code, private, root])
    clip = root / 'fixture.mkv'
    run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
         'testsrc2=size=64x64:rate=25:duration=0.2', '-c:v', 'mpeg4', clip])
    output = run([root / 'usr/bin/mpv-decklink', '--vo=null', '--ao=null', '--osc=no', clip])
    assert 'VO: [null]' in output, output
    run(['desktop-file-validate', root / 'usr/share/applications/bmdmpv.desktop'])
    contents = run(['dpkg-deb', '--contents', args.package])
    assert all('root/root' in line for line in contents.splitlines())
    print('PASS: package metadata/checksums, launchers, private libraries, GUI imports, null video playback and desktop entry')
