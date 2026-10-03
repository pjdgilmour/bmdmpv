# SPDX-License-Identifier: LGPL-2.1-or-later
"""Media source identifiers. Only YouTube video URLs are accepted remotely."""
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit


def is_remote(value):
    return bool(re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', str(value)))


def youtube_url(value):
    value = str(value).strip()
    parsed = urlsplit(value)
    if (parsed.scheme not in ('http', 'https') or parsed.username or parsed.password or
            parsed.port is not None or any(ord(c) < 32 for c in value)):
        raise ValueError('Cole um link HTTP/HTTPS de um vídeo do YouTube.')
    host = (parsed.hostname or '').lower()
    parts = parsed.path.strip('/').split('/')
    video = None
    if host in ('youtu.be', 'www.youtu.be') and len(parts) == 1:
        video = parts[0]
    elif host in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com',
                  'youtube-nocookie.com', 'www.youtube-nocookie.com'):
        if parsed.path == '/watch':
            video = parse_qs(parsed.query).get('v', [None])[0]
        elif len(parts) == 2 and parts[0] in ('shorts', 'embed', 'live'):
            video = parts[1]
    if not video or not re.fullmatch(r'[A-Za-z0-9_-]{11}', video):
        raise ValueError('Use o link de um vídeo do YouTube (watch, youtu.be ou Shorts), não de um canal ou playlist.')
    return 'https://www.youtube.com/watch?v=' + video


def normalize_source(value):
    if is_remote(value):
        return youtube_url(value)
    return str(Path(value).expanduser().resolve())


def source_name(value):
    return 'YouTube · ' + parse_qs(urlsplit(value).query).get('v', ['vídeo'])[0] if is_remote(value) else Path(value).name
