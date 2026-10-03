#!/usr/bin/env python3
"""Build test doubles from the installed SDK interfaces, without a device."""
import os
from pathlib import Path
import re
import subprocess

base = Path(__file__).resolve().parent.parent
sdk = Path(os.environ.get('DECKLINK_SDK_INCLUDE',
    '/home/paulo/Blackmagic DeckLink SDK 16.0/Linux/include'))
out = base / 'build' / 'bridge-tests'
out.mkdir(parents=True, exist_ok=True)
headers = '\n'.join(p.read_text() for p in sdk.glob('*.h') if '_v' not in p.name)
headers = re.sub(r'/\*.*?\*/|//[^\n]*', '', headers, flags=re.S)
interfaces = ['IDeckLink', 'IDeckLinkIterator', 'IDeckLinkOutput',
              'IDeckLinkConfiguration', 'IDeckLinkDisplayMode',
              'IDeckLinkMutableVideoFrame', 'IDeckLinkVideoFrame',
              'IDeckLinkVideoBuffer']
classes = ['#include <DeckLinkAPI.h>\n#include <cassert>\n']
for name in interfaces:
    methods = []
    parent = name
    while parent != 'IUnknown':
        match = re.search(r'class BMD_PUBLIC ' + parent + r' : public (\w+)\s*\{(.*?)\n\};', headers, re.S)
        if not match:
            raise RuntimeError(f'Cannot find SDK interface {parent}')
        parent, body = match.groups()
        methods += re.findall(r'virtual\s+(\w+)\s+(\w+)\s*(\([^;]*?\))\s*= 0;', body)
    classes.append(f'class Stub{name} : public {name} {{\npublic:\n')
    classes.append('int refs = 0;\nHRESULT QueryInterface(REFIID, void **p) override { *p = nullptr; return E_NOINTERFACE; }\n'
                   'ULONG AddRef() override { return ++refs; }\n'
                   'ULONG Release() override { assert(refs > 0); return --refs; }\n')
    for result, method, args in methods:
        value = 'E_NOTIMPL' if result == 'HRESULT' else '{}'
        classes.append(f'{result} {method}{args} override {{ return {value}; }}\n')
    classes.append('};\n')
(out / 'stubs.h').write_text(''.join(classes))
exe = out / 'test-bridge'
subprocess.run(['c++', '-std=c++20', '-g', '-fsanitize=address,undefined',
                '-fno-omit-frame-pointer', '-I'+str(sdk), '-I'+str(out),
                '-I'+str(base/'mpv'), str(base/'tests/test_bridge.cpp'),
                str(base/'mpv/video/out/decklink_bridge.cpp'), '-o', str(exe)], check=True)
# LeakSanitizer cannot run under all sandbox/ptrace environments; reference
# balance is asserted explicitly, while address/undefined checks remain active.
subprocess.run([str(exe)], check=True,
               env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
