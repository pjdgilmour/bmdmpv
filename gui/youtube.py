# SPDX-License-Identifier: LGPL-2.1-or-later
"""Bounded, cancellable metadata extraction using the installed yt-dlp."""
import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from .sources import youtube_url

# Keep HDR out of the SDR-only DeckLink output. Choose actual selected formats,
# not the original upload dimensions. mpv re-extracts these format IDs on play.
FORMAT = 'bv[dynamic_range=SDR][height<=2160]+ba/b[dynamic_range=SDR][height<=2160]'
BROWSERS = {'Sem cookies': '', 'Firefox': 'firefox', 'Chrome': 'chrome',
            'Chromium': 'chromium', 'Edge': 'edge', 'Brave': 'brave',
            'Opera': 'opera', 'Vivaldi': 'vivaldi'}


def extractor_options(browser=''):
    """Share authentication and JS setup between metadata and mpv's ytdl hook."""
    if browser not in BROWSERS.values():
        raise ValueError('Navegador de cookies inválido.')
    options = {'remote-components': 'ejs:github'}
    for runtime, executable in [('deno', 'deno'), ('node', 'node'), ('bun', 'bun'), ('quickjs', 'qjs')]:
        if shutil.which(executable):
            options['js-runtimes'] = runtime
            break
    if browser:
        options['cookies-from-browser'] = browser
    return options


class ProbeCancelled(Exception):
    pass


def extract(url, cancel=None, timeout=60, browser=''):
    url = youtube_url(url)
    executable = shutil.which('yt-dlp')
    if not executable:
        raise ValueError('yt-dlp não encontrado no PATH. Instale-o para abrir vídeos do YouTube.')
    cancel = cancel or threading.Event()
    if cancel.is_set():
        raise ProbeCancelled()
    command = [executable, '--ignore-config', '--no-playlist', '--skip-download',
               '--no-cache-dir', '--no-warnings', '--socket-timeout', '10', '--retries', '1',
               '--extractor-retries', '1', '--dump-single-json', '--format', FORMAT]
    for key, value in extractor_options(browser).items():
        command += ['--' + key, value]
    command += ['--', url]
    proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, errors='replace', start_new_session=True)
    try:
        deadline = time.monotonic() + timeout
        while True:
            if cancel.is_set():
                raise ProbeCancelled()
            if time.monotonic() >= deadline:
                raise ValueError('O YouTube não respondeu em 60 segundos. Verifique a conexão e tente novamente.')
            try:
                output, error = proc.communicate(timeout=.1)
                break
            except subprocess.TimeoutExpired:
                pass
        if proc.returncode:
            detail = error.strip()[-3000:]
            hint = (' Confira também se está conectado ao YouTube no navegador selecionado.' if browser else '')
            raise ValueError('Não foi possível consultar o YouTube. Verifique o link, a conexão e a versão do yt-dlp.' + hint + '\n\n' + detail)
        try:
            return json.loads(output)
        except ValueError as exc:
            raise ValueError('O yt-dlp retornou metadados inválidos.') from exc
    finally:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                proc.communicate(timeout=1)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.communicate()


def parse_youtube(url, data):
    from .core import Media, number
    if not isinstance(data, dict) or data.get('_type', 'video') != 'video':
        raise ValueError('O link precisa identificar um único vídeo do YouTube.')
    if data.get('is_live') or data.get('live_status') in ('is_live', 'is_upcoming', 'post_live'):
        raise ValueError('Esta versão aceita vídeos publicados; transmissões ao vivo/agendadas ainda não são suportadas.')
    formats = data.get('requested_formats') or [data]
    video = next((f for f in formats if f.get('vcodec') not in (None, 'none')), None)
    if not video or not video.get('width') or not video.get('height'):
        raise ValueError('Não foi encontrado um formato de vídeo SDR compatível.')
    if video.get('dynamic_range', data.get('dynamic_range')) != 'SDR':
        raise ValueError('O YouTube não ofereceu uma versão SDR compatível para este vídeo.')
    format_id = '+'.join(str(f.get('format_id', '')) for f in formats)
    if not re.fullmatch(r'[A-Za-z0-9_.-]+(?:\+[A-Za-z0-9_.-]+)*', format_id):
        raise ValueError('Identificadores de formato inválidos retornados pelo yt-dlp.')
    return Media(youtube_url(url), number(video['width']), number(video['height']),
                 number(video.get('fps')), number(data.get('duration')),
                 any(f.get('acodec') != 'none' for f in formats), True,
                 title=str(data.get('title') or 'Vídeo do YouTube'), ytdl_format=format_id)


def probe_youtube(url, cancel=None, browser=''):
    media = parse_youtube(url, extract(url, cancel, browser=browser))
    media.youtube_browser = browser
    return media
