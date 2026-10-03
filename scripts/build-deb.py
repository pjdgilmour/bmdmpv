#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Package an existing Debian 13 amd64 build, without sudo or system changes."""
import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile

BASE = Path(__file__).resolve().parents[1]


def run(args, **kwargs):
    return subprocess.check_output([str(a) for a in args], text=True, **kwargs).strip()


def copy(src, dst, mode=0o644):
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    dst.chmod(mode)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', default='0.1.1-1')
    args = parser.parse_args()
    if not re.fullmatch(r'[0-9][A-Za-z0-9.+~]*-[0-9]+', args.version):
        parser.error('Use a Debian version such as 0.1.1-1.')
    release = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
    if release.get('ID', '').strip('"') != 'debian' or release.get('VERSION_ID', '').strip('"') != '13':
        parser.error('This packaging recipe currently targets Debian 13 only.')
    arch = run(['dpkg', '--print-architecture'])
    if arch != 'amd64':
        parser.error('This build currently targets amd64 only.')
    patchelf = os.environ.get('PATCHELF') or shutil.which('patchelf')
    if not patchelf:
        local = BASE / '.deps/patchelf/usr/bin/patchelf'
        patchelf = str(local) if local.is_file() else None
    if not patchelf:
        parser.error('Install patchelf or set PATCHELF to a locally extracted executable.')
    for tool in ('dpkg-deb', 'dpkg-shlibdeps', 'strip', 'desktop-file-validate'):
        if not shutil.which(tool):
            parser.error('Missing packaging tool: ' + tool)
    placebo = BASE / '.deps/local/lib/libplacebo.so.374'
    sources = BASE / '.deps/libplacebo'
    for path in (BASE / 'build-mpv/mpv', BASE / 'build/decklink-probe', placebo, sources / 'LICENSE'):
        if not path.is_file():
            parser.error('Build prerequisite missing: ' + str(path))
    sdk = Path(os.environ.get('DECKLINK_SDK_INCLUDE', '/home/paulo/Blackmagic DeckLink SDK 16.0/Linux/include'))
    dispatch = (sdk / 'DeckLinkAPIDispatch.cpp').read_text()
    license_text = dispatch.split('/* -LICENSE-START-', 1)[1].split('** -LICENSE-END-', 1)[0]
    epoch = int(os.environ.get('SOURCE_DATE_EPOCH') or run(['git', 'log', '-1', '--format=%ct'], cwd=BASE))
    os.environ['SOURCE_DATE_EPOCH'] = str(epoch)
    dist = BASE / 'dist'
    dist.mkdir(exist_ok=True)
    package = dist / f'bmdmpv_{args.version}_{arch}.deb'
    archive = dist / f'bmdmpv_{args.version}_sources.tar.xz'
    with tempfile.TemporaryDirectory(prefix='bmdmpv-deb-') as tmp:
        work = Path(tmp)
        root = work / 'package'
        control = root / 'DEBIAN'
        control.mkdir(parents=True)
        private = root / 'usr/lib/bmdmpv'
        doc = root / 'usr/share/doc/bmdmpv'
        for name, src in [('mpv', BASE / 'build-mpv/mpv'),
                          ('decklink-probe', BASE / 'build/decklink-probe'),
                          ('lib/libplacebo.so.374', placebo)]:
            copy(src, private / name, 0o755)
            run(['strip', '--strip-unneeded', private / name])
        run([patchelf, '--set-rpath', '$ORIGIN/lib', private / 'mpv'])
        run([patchelf, '--remove-rpath', private / 'lib/libplacebo.so.374'])
        for src in (BASE / 'gui').glob('*.py'):
            copy(src, private / 'gui' / src.name)
        for name in ('bmdmpv-gui', 'mpv-decklink'):
            copy(BASE / name, private / name, 0o755)
            link = root / 'usr/bin' / name
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to('../lib/bmdmpv/' + name)
        copy(BASE / 'packaging/bmdmpv.desktop', root / 'usr/share/applications/bmdmpv.desktop')
        run(['desktop-file-validate', root / 'usr/share/applications/bmdmpv.desktop'])
        copy(BASE / 'packaging/bmdmpv.svg', root / 'usr/share/icons/hicolor/scalable/apps/bmdmpv.svg')
        copy(BASE / 'completions/mpv-decklink', root / 'usr/share/bash-completion/completions/mpv-decklink')
        for name in ('copyright', 'README.Debian'):
            copy(BASE / 'packaging' / name, doc / name)
        copy(BASE / 'README.rst', doc / 'README.rst')
        copy(BASE / 'mpv/Copyright', doc / 'mpv-Copyright')
        copy(BASE / 'mpv/LICENSE.GPL', doc / 'mpv-LICENSE.GPL')
        copy(BASE / 'mpv/LICENSE.LGPL', doc / 'mpv-LICENSE.LGPL')
        copy(sources / 'LICENSE', doc / 'libplacebo-LICENSE')
        (doc / 'DeckLink-Dispatch-License').write_text(license_text)

        # Use dpkg's symbol/shlibs data for actual linked system dependencies.
        debian = work / 'debian'
        debian.mkdir()
        (debian / 'control').write_text('Source: bmdmpv\nSection: video\nPriority: optional\n'
            'Maintainer: bmdmpv contributors <bmdmpv@localhost>\n\n'
            'Package: bmdmpv\nArchitecture: amd64\nDescription: Blackmagic HDMI player\n')
        local_shlibs = debian / 'shlibs.local'
        local_shlibs.write_text(f'libplacebo 374 bmdmpv (= {args.version})\n')
        deps = run(['dpkg-shlibdeps', '-O', '-xbmdmpv', '-L' + str(local_shlibs),
                    '-l' + str(private / 'lib'), '-e' + str(private / 'mpv'),
                    '-e' + str(private / 'decklink-probe'),
                    '-e' + str(private / 'lib/libplacebo.so.374')], cwd=work)
        deps = next(line.split('=', 1)[1] for line in deps.splitlines() if line.startswith('shlibs:Depends='))
        installed_size = sum(p.stat().st_size for p in root.rglob('*') if p.is_file() and not p.is_symlink())
        (control / 'control').write_text(
            f'Package: bmdmpv\nVersion: {args.version}\nArchitecture: {arch}\n'
            'Section: video\nPriority: optional\nMaintainer: bmdmpv contributors <bmdmpv@localhost>\n'
            f'Installed-Size: {(installed_size + 1023) // 1024}\n'
            f'Depends: python3 (>= 3.10), python3-tk, ffmpeg, desktopvideo (>= 16.0), {deps}\n'
            'Recommends: yt-dlp, bash-completion\nSuggests: deno | nodejs (>= 22)\n'
            'Description: HDMI media player for Blackmagic DeckLink and Intensity\n'
            ' Python/Tk desktop controller with playlists, profiles and YouTube support.\n'
            ' Includes a private mpv build with DeckLink video/audio output and libplacebo.\n'
            ' Targets Debian 13 amd64. Requires the external Blackmagic Desktop Video driver.\n')
        (control / 'md5sums').write_text(''.join(
            hashlib.md5(p.read_bytes()).hexdigest() + '  ' + str(p.relative_to(root)) + '\n'
            for p in sorted(root.rglob('*')) if p.is_file() and not p.is_symlink() and control not in p.parents))
        # Normalize file ownership and build time in the archive, never on the host.
        for path in root.rglob('*'):
            os.utime(path, (epoch, epoch), follow_symlinks=False)
        os.utime(root, (epoch, epoch))
        print(run(['dpkg-deb', '--root-owner-group', '--build', root, package]))

    # Ship the corresponding modified sources alongside the binary package.
    def tar_filter(info):
        if any(part in {'.git', '__pycache__'} for part in Path(info.name).parts) or info.name.endswith('.pyc'):
            return None
        info.uid = info.gid = 0
        info.uname = info.gname = 'root'
        info.mtime = epoch
        return info
    with tarfile.open(archive, 'w:xz') as tar:
        prefix = 'bmdmpv-' + args.version
        names = ['README.rst', 'gui', 'mpv', 'scripts', 'tests', 'packaging', 'completions',
                 'bmdmpv-gui', 'mpv-decklink', 'build-mpv.sh', 'build-probe.sh',
                 'bootstrap-local.sh', 'install-completion.sh']
        for name in names:
            tar.add(BASE / name, arcname=prefix + '/' + name, filter=tar_filter)
        tar.add(sources, arcname=prefix + '/third_party/libplacebo', filter=tar_filter)
        for build, name in [('build-mpv', 'mpv'), ('.deps/libplacebo-build', 'libplacebo')]:
            tar.add(BASE / build / 'meson-info/intro-buildoptions.json',
                    arcname=prefix + '/build-options-' + name + '.json', filter=tar_filter)
    sums = dist / f'bmdmpv_{args.version}_SHA256SUMS'
    sums.write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n'
                           for p in (package, archive)))
    print(f'Created: {package}\nSources: {archive}\nChecksums: {sums}')


if __name__ == '__main__':
    main()
