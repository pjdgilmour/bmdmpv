# SPDX-License-Identifier: LGPL-2.1-or-later
"""Discovery, mode selection and asynchronous mpv IPC; independent of Tk."""
from dataclasses import dataclass, field
from fractions import Fraction
import json
import math
from pathlib import Path
import queue
import re
import socket
import subprocess
import tempfile
import threading
import time

from .library import HWDECS

BASE = Path(__file__).resolve().parent.parent
MPV = BASE / 'build-mpv/mpv'


@dataclass(frozen=True)
class Mode:
    code: str
    width: int
    height: int
    fps: float
    name: str

    @property
    def label(self):
        return f'{self.width} × {self.height} · {self.fps:.3f} fps  [{self.code}]'


@dataclass
class Card:
    index: int
    name: str
    modes: list = field(default_factory=list)

    @property
    def label(self):
        return f'{self.index} · {self.name}'


@dataclass(frozen=True)
class Audio:
    label: str
    ao: str
    device: str = 'auto'


@dataclass
class Media:
    path: str
    width: float
    height: float
    fps: float
    duration: float
    audio: bool
    video: bool
    interlaced: bool = False
    unsupported_color: bool = False
    video_id: int | None = None


def run_text(args, timeout=15):
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, errors='replace', timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or
                           f'Comando terminou com código {result.returncode}.')
    return result.stdout


def parse_cards(text):
    cards = []
    for line in text.splitlines():
        card = re.match(r'^Device (\d+): (.+)$', line)
        mode = re.match(r'^\s+(\S{4})\s+(\d+)x(\d+)\s+([\d.]+) fps\s+(.+)$', line)
        if card:
            cards.append(Card(int(card[1]), card[2]))
        elif mode and cards:
            cards[-1].modes.append(Mode(mode[1], int(mode[2]), int(mode[3]), float(mode[4]), mode[5]))
    return [c for c in cards if c.modes]


def discover_cards():
    return parse_cards(run_text([str(BASE / 'build/decklink-probe')]))


def parse_audio(text, backends):
    choices = [Audio('Intensity / Blackmagic · HDMI', 'decklink')]
    for ao, name in [('pipewire', 'PipeWire'), ('pulse', 'PulseAudio')]:
        if ao in backends:
            choices.append(Audio(f'Padrão do sistema · {name}', ao))
    for device, label in re.findall(r"^\s+'(.*)' \((.*)\)$", text, re.MULTILINE):
        ao = device.split('/')[0]
        if '/' in device and ao in ('pipewire', 'pulse') and ao in backends:
            choices.append(Audio(f'{label} · {ao}', ao, device))
    choices.append(Audio('Sem áudio', 'none'))
    return choices


def discover_audio():
    backends = run_text([str(MPV), '--no-config', '--ao=help'])
    devices = run_text([str(MPV), '--no-config', '--audio-device=help'], timeout=12)
    return parse_audio(devices, backends)


def number(value, default=0):
    try:
        n = float(Fraction(str(value).replace(':', '/')))
        return n if math.isfinite(n) else default
    except (ValueError, ZeroDivisionError):
        return default


def parse_media(path, data):
    streams = data.get('streams', [])
    videos = [s for s in streams if s.get('codec_type') == 'video'
              and not s.get('disposition', {}).get('attached_pic')]
    video = next((s for s in videos if s.get('disposition', {}).get('default')), videos[0] if videos else {})
    width, height = number(video.get('width')), number(video.get('height'))
    width *= number(video.get('sample_aspect_ratio'), 1) or 1
    rotation = next((s.get('rotation', 0) for s in video.get('side_data_list', [])
                     if 'rotation' in s), video.get('tags', {}).get('rotate', 0))
    if abs(number(rotation)) % 180 == 90:
        width, height = height, width
    interlaced = video.get('field_order') in ('tt', 'bb', 'tb', 'bt')
    fps = number(video.get('avg_frame_rate')) or number(video.get('r_frame_rate'))
    hdr = (video.get('color_transfer') in ('smpte2084', 'arib-std-b67') or
           video.get('color_primaries') == 'bt2020' or
           any('DOVI' in s.get('side_data_type', '') for s in video.get('side_data_list', [])))
    return Media(str(path), width, height, fps * (2 if interlaced else 1),
                 number(data.get('format', {}).get('duration')),
                 any(s.get('codec_type') == 'audio' for s in streams), bool(video),
                 interlaced, hdr, (1 + [s for s in streams if s.get('codec_type') == 'video'].index(video)) if video else None)


def probe_media(path):
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise ValueError('Selecione um arquivo de mídia existente.')
    data = json.loads(run_text(['ffprobe', '-v', 'error', '-show_streams',
                               '-show_format', '-of', 'json', str(path)], timeout=25))
    media = parse_media(path, data)
    if not media.video and not media.audio:
        raise ValueError('O arquivo não contém vídeo nem áudio reconhecido.')
    return media


def choose_mode(modes, media, height=None):
    candidates = [m for m in modes if height is None or m.height == height]
    if not candidates:
        raise ValueError('A placa não oferece modos nessa resolução.')
    fps = media.fps or 30
    width, h = (media.width or 1920), (media.height or 1080)

    def score(m):
        ratio = m.fps / fps
        exact = abs(m.fps - fps) < .002
        multiple = ratio >= 1 and abs(ratio - round(ratio)) < .0002
        cadence = 0 if exact else (1 if multiple else 2)
        fits = m.width >= width - 1 and m.height >= h - 1
        area = m.width * m.height
        return (cadence, 0 if cadence < 2 else abs(m.fps - fps),
                0 if fits else 1, area if fits else -area, abs(m.fps - fps))

    return min(candidates, key=score)


def mode_note(mode, media):
    parts = []
    if not media.video:
        parts.append('Arquivo de áudio; saída de vídeo sem imagem do arquivo.')
    elif media.width and media.height:
        scale = min(mode.width / media.width, mode.height / media.height)
        parts.append('Tamanho original' if abs(scale - 1) < .005 else
                     ('Upscale' if scale > 1 else 'Downscale') + ' por software (mpv)')
    if media.fps:
        if abs(mode.fps - media.fps) >= .002:
            parts.append(f'Cadência adaptada: {media.fps:.3f} → {mode.fps:.3f} fps')
        else:
            parts.append('Taxa de quadros preservada')
    else:
        parts.append('FPS não informado; referência automática de 30 fps')
    if media.interlaced:
        parts.append('Desentrelaçamento ativado')
    return ' · '.join(parts)


def playback_args(media, card, mode, audio, framing='fit', volume=80, delay=0,
                  loop=False, mute=False, hwdec='no'):
    if media.unsupported_color:
        raise ValueError('Este backend aceita SDR. Converta HDR/BT.2020/Dolby Vision para BT.709 SDR antes de reproduzir.')
    if framing not in ('fit', 'fill', 'stretch'):
        raise ValueError('Enquadramento inválido.')
    if not math.isfinite(delay) or not -10 <= delay <= 10:
        raise ValueError('O atraso deve estar entre −10 e +10 segundos.')
    if hwdec not in HWDECS:
        raise ValueError('Este backend requer decodificação CPU ou GPU com cópia para RAM.')
    args = [str(MPV), '--no-config', '--vo=decklink', f'--hwdec={hwdec}',
            f'--vo-decklink-device={card.index}', f'--vo-decklink-mode={mode.code}',
            '--keep-open=yes', '--input-terminal=no', '--terminal=no',
            '--osd-level=0', f'--volume={float(volume):.1f}', f'--audio-delay={delay}',
            f'--mute={"yes" if mute else "no"}', f'--loop-file={"inf" if loop else "no"}',
            f'--keepaspect={"no" if framing == "stretch" else "yes"}',
            f'--panscan={1 if framing == "fill" else 0}']
    if audio.ao == 'none':
        args.append('--audio=no')
    else:
        args += [f'--ao={audio.ao}', f'--audio-device={audio.device}', '--audio-fallback-to-null=no']
    if media.video:
        if media.video_id is not None:
            args.append(f'--vid={media.video_id}')
    else:
        args += ['--vid=no', '--force-window=immediate']
    if media.interlaced:
        args.append('--deinterlace=yes')
    return args + ['--', media.path]


class Player:
    """One owned child process. All I/O runs off the UI thread; events are queued."""
    PROPERTIES = ('time-pos', 'duration', 'pause', 'eof-reached', 'volume', 'mute',
                  'audio-delay', 'current-ao', 'current-vo', 'hwdec-current')

    def __init__(self, args, events):
        self.args = args
        self.events = events
        self.commands = queue.Queue()
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def command(self, *args):
        self.commands.put(args)

    def stop(self):
        self.stopping.set()

    def emit(self, kind, value):
        self.events.put((self, kind, value))

    def _run(self):
        proc = None
        sock = None
        error = None
        returncode = None
        log = ''
        try:
            if self.stopping.is_set():
                return
            with tempfile.TemporaryDirectory(prefix='bmdmpv-gui-', dir='/tmp') as tmp:
                ipc = str(Path(tmp) / 'ipc')
                logpath = Path(tmp) / 'mpv.log'
                args = self.args[:]
                separator = args.index('--')
                args[separator:separator] = ['--input-ipc-server=' + ipc, '--log-file=' + str(logpath)]
                with (Path(tmp) / 'console.log').open('w+') as console:
                    try:
                        proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=console, stderr=console)
                        deadline = time.monotonic() + 12
                        while not self.stopping.is_set():
                            if proc.poll() is not None:
                                raise RuntimeError('O mpv encerrou antes de abrir a reprodução.')
                            try:
                                sock = socket.socket(socket.AF_UNIX)
                                sock.settimeout(.1)
                                sock.connect(ipc)
                                break
                            except (FileNotFoundError, ConnectionRefusedError):
                                sock.close()
                                sock = None
                                if time.monotonic() > deadline:
                                    raise RuntimeError('O mpv não respondeu em 12 segundos.')
                                self.stopping.wait(.05)
                        if sock:
                            for i, prop in enumerate(self.PROPERTIES):
                                self.command('observe_property', i, prop)
                            self.emit('connected', None)
                            buffer = b''
                            request_id = 0
                            while not self.stopping.is_set() and proc.poll() is None:
                                for _ in range(50):
                                    try:
                                        command = self.commands.get_nowait()
                                    except queue.Empty:
                                        break
                                    request_id += 1
                                    sock.sendall((json.dumps({'command': command, 'request_id': request_id}) + '\n').encode())
                                try:
                                    chunk = sock.recv(65536)
                                except socket.timeout:
                                    continue
                                if not chunk:
                                    break
                                buffer += chunk
                                while b'\n' in buffer:
                                    line, buffer = buffer.split(b'\n', 1)
                                    event = json.loads(line)
                                    if event.get('event') == 'property-change':
                                        self.emit('property', (event['name'], event.get('data')))
                                    elif event.get('event') == 'end-file' and event.get('reason') == 'error':
                                        error = 'Falha na reprodução: ' + event.get('file_error', 'consulte o diagnóstico.')
                                        self.stopping.set()
                                    elif event.get('error') not in (None, 'success'):
                                        self.emit('command-error', event['error'])
                    finally:
                        if proc:
                            if proc.poll() is None and sock:
                                try:
                                    sock.sendall(b'{"command":["quit"]}\n')
                                except OSError:
                                    pass
                            try:
                                proc.wait(timeout=3)
                            except subprocess.TimeoutExpired:
                                proc.terminate()
                                try:
                                    proc.wait(timeout=2)
                                except subprocess.TimeoutExpired:
                                    proc.kill()
                                    proc.wait(timeout=2)
                            returncode = proc.returncode
                        source = logpath if logpath.exists() else Path(tmp) / 'console.log'
                        with source.open('rb') as stream:
                            stream.seek(0, 2)
                            stream.seek(max(0, stream.tell() - 64000))
                            log = stream.read().decode('utf-8', 'replace')
        except Exception as exc:
            error = str(exc)
        finally:
            if sock:
                sock.close()
            self.emit('finished', {'code': returncode, 'error': error, 'log': log})
