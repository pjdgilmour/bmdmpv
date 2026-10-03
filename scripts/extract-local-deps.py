#!/usr/bin/env python3
"""Extract Debian development packages without modifying the system."""
from pathlib import Path
import subprocess

base = Path(__file__).resolve().parent.parent / '.deps'
root = base / 'root'
root.mkdir(parents=True, exist_ok=True)
for deb in (base / 'debs').glob('*.deb'):
    if deb.name.startswith('libplacebo-dev_'):
        continue  # Built separately; older headers would shadow the local build.
    subprocess.run(['dpkg-deb', '-x', str(deb), str(root)], check=True)
for pc in root.glob('usr/lib/*/pkgconfig/*.pc'):
    text = pc.read_text()
    for variable in ('prefix', 'libdir', 'includedir'):
        text = text.replace(f'{variable}=/usr', f'{variable}={root}/usr')
    pc.write_text(text)
for lib in root.glob('usr/lib/*/*.so'):
    if lib.is_symlink() and not lib.exists():
        target = Path('/usr/lib') / lib.parent.name / lib.readlink().name
        if target.exists():
            lib.unlink()
            lib.symlink_to(target)
