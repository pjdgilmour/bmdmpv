# SPDX-License-Identifier: LGPL-2.1-or-later
"""Local playlists and versioned, atomic profile persistence."""
import json
import math
import os
from pathlib import Path
import tempfile
from .sources import is_remote, normalize_source
from .youtube import BROWSERS

HWDECS = {'no', 'auto-copy', 'nvdec-copy', 'vaapi-copy'}
REPEATS = {'none', 'file', 'playlist'}


class Playlist:
    def __init__(self, paths=()):
        self.paths = [normalize_source(p) for p in paths]
        self.index = 0 if self.paths else -1

    def append(self, paths):
        self.paths.extend([normalize_source(p) for p in paths])
        if self.index < 0 and self.paths:
            self.index = 0

    def remove(self, index):
        self.paths.pop(index)
        if index < self.index:
            self.index -= 1
        self.index = min(self.index, len(self.paths) - 1)

    def move(self, index, delta):
        target = index + delta
        if not 0 <= target < len(self.paths):
            return index
        item = self.paths.pop(index)
        self.paths.insert(target, item)
        if self.index == index:
            self.index = target
        elif index < self.index <= target:
            self.index -= 1
        elif target <= self.index < index:
            self.index += 1
        return target

    def adjacent(self, delta=1, wrap=False):
        if not self.paths:
            return None
        index = self.index + delta
        if 0 <= index < len(self.paths):
            return index
        return index % len(self.paths) if wrap else None


def read_playlist(path):
    path = Path(path).expanduser().resolve()
    text = path.read_text(encoding='utf-8-sig')
    paths = []
    for line in text.splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        if is_remote(line):
            paths.append(normalize_source(line))
            continue
        item = Path(line).expanduser()
        paths.append(str((item if item.is_absolute() else path.parent / item).resolve()))
    return Playlist(paths)


def write_playlist(path, playlist):
    for item in playlist.paths:
        if '\n' in item or '\r' in item:
            raise ValueError('M3U8 não aceita nomes de arquivo com quebras de linha.')
    atomic_write(Path(path), '#EXTM3U\n' + ''.join(p + '\n' for p in playlist.paths))


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.' + path.name + '-', delete=False) as stream:
            tmp = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if tmp:
            tmp.unlink(missing_ok=True)


def validate_profile(profile):
    if not isinstance(profile, dict):
        raise ValueError('Perfil inválido.')
    required = {'card_index', 'card_name', 'target', 'mode', 'audio_ao', 'audio_device',
                'framing', 'volume', 'mute', 'delay', 'repeat', 'hwdec'}
    if not required <= set(profile) or set(profile) - required - {'youtube_browser', 'prefer_high_refresh'}:
        raise ValueError('O perfil tem campos ausentes ou desconhecidos.')
    if profile.get('youtube_browser', '') not in BROWSERS.values():
        raise ValueError('Navegador de cookies inválido no perfil.')
    if type(profile.get('prefer_high_refresh', False)) is not bool:
        raise ValueError('Preferência de frequência HDMI inválida no perfil.')
    if type(profile['card_index']) is not int or not 0 <= profile['card_index'] <= 255:
        raise ValueError('Índice de placa inválido no perfil.')
    for key in ('card_name', 'mode', 'audio_ao', 'audio_device', 'framing', 'repeat', 'hwdec'):
        if not isinstance(profile[key], str):
            raise ValueError('Campo inválido no perfil: ' + key)
    if profile['target'] not in ('auto', '720', '1080', '2160', 'manual'):
        raise ValueError('Resolução inválida no perfil.')
    if len(profile['mode']) != 4:
        raise ValueError('Modo HDMI inválido no perfil.')
    if profile['audio_ao'] not in ('decklink', 'pipewire', 'pulse', 'none'):
        raise ValueError('Saída de áudio inválida no perfil.')
    if profile['framing'] not in ('fit', 'fill', 'stretch') or profile['hwdec'] not in HWDECS:
        raise ValueError('Enquadramento ou decodificador inválido no perfil.')
    if profile['repeat'] not in REPEATS or type(profile['mute']) is not bool:
        raise ValueError('Repetição ou mute inválido no perfil.')
    for key, low, high in [('volume', 0, 100), ('delay', -10, 10)]:
        value = profile[key]
        if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError('Valor inválido no perfil: ' + key)
    return dict(profile, youtube_browser=profile.get('youtube_browser', ''),
                prefer_high_refresh=profile.get('prefer_high_refresh', False))


class ProfileStore:
    def __init__(self, path=None):
        config = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
        self.path = Path(path) if path is not None else config / 'bmdmpv/profiles.json'

    def read(self):
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if (not isinstance(data, dict) or type(data.get('version')) is not int or data.get('version') != 1 or
                    not isinstance(data.get('profiles'), dict)):
                raise ValueError('Versão ou estrutura de perfis inválida.')
            for name, profile in data['profiles'].items():
                if not isinstance(name, str) or not name.strip() or len(name) > 80:
                    raise ValueError('Nome de perfil inválido.')
                validate_profile(profile)
            return data['profiles']
        except (ValueError, TypeError) as exc:
            raise ValueError(f'Não foi possível ler {self.path}: {exc}. O arquivo foi preservado.') from exc

    def save(self, name, profile):
        name = name.strip()
        if not name or len(name) > 80:
            raise ValueError('Use um nome de perfil com 1 a 80 caracteres.')
        profile = validate_profile(profile)
        profiles = self.read()
        profiles[name] = profile
        self._write(profiles)
        return name

    def delete(self, name):
        profiles = self.read()
        profiles.pop(name, None)
        self._write(profiles)

    def _write(self, profiles):
        atomic_write(self.path, json.dumps({'version': 1, 'profiles': profiles},
                                          ensure_ascii=False, indent=2) + '\n')
