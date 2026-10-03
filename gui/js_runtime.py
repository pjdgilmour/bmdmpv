# SPDX-License-Identifier: LGPL-2.1-or-later
"""Find compatible yt-dlp JS runtimes even from a desktop's minimal PATH."""
import os
from pathlib import Path
import re
import subprocess


def candidates(executable):
    home = Path.home()
    directories = [Path(p) for p in os.environ.get('PATH', '').split(os.pathsep) if p and Path(p).is_absolute()]
    directories += [home / '.local/bin', home / '.deno/bin', home / '.bun/bin']
    seen = set()
    for directory in directories:
        path = directory / executable
        if path in seen:
            continue
        seen.add(path)
        if path.is_file() and os.access(path, os.X_OK):
            yield path


def compatible(name, text):
    if name == 'quickjs':
        if re.search(r'QuickJS-ng\s+version\s+\d+\.', text, re.I):
            return True
        match = re.search(r'QuickJS.*?(\d{4})-(\d{1,2})-(\d{1,2})', text, re.I)
        return bool(match and tuple(map(int, match.groups())) >= (2023, 12, 9))
    match = re.search(r'(\d+)\.(\d+)\.(\d+)', text)
    if not match:
        return False
    version = tuple(map(int, match.groups()))
    minimum = {'deno': (2, 3, 0), 'node': (22, 0, 0), 'bun': (1, 2, 11)}[name]
    return version >= minimum and (name != 'bun' or version <= (1, 3, 14))


def find_runtime():
    details = []
    for name, executable in [('deno', 'deno'), ('node', 'node'), ('quickjs', 'qjs'), ('bun', 'bun')]:
        for path in candidates(executable):
            try:
                result = subprocess.run([str(path), '--help' if name == 'quickjs' else '--version'],
                                        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True, errors='replace', timeout=2)
                if result.returncode == 0 and compatible(name, result.stdout):
                    return name + ':' + str(path)
                details.append(str(path) + ': versão incompatível ou não identificada')
            except (OSError, subprocess.TimeoutExpired):
                details.append(str(path) + ': não foi possível executar')
    raise ValueError('O YouTube precisa de um runtime JavaScript compatível: Deno >= 2.3 ou Node >= 22. '
                     'Instale uma versão compatível no PATH, em ~/.local/bin ou em ~/.deno/bin.\n' + '\n'.join(details))
