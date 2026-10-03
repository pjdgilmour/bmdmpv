#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gui.js_runtime import compatible, find_runtime


class RuntimeTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.home = self.base / 'home'
        self.system = self.base / 'system'
        for p in [patch('gui.js_runtime.Path.home', return_value=self.home),
                  patch.dict(os.environ, PATH=str(self.system))]:
            p.start()
            self.addCleanup(p.stop)

    def binary(self, path, version):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('#!/bin/sh\nprintf "%s\\n" "' + version + '"\n')
        path.chmod(0o755)
        return path

    def test_desktop_path_finds_local_deno_without_changing_environment(self):
        deno = self.binary(self.home / '.local/bin/deno', 'deno 2.9.6')
        self.assertEqual(find_runtime(), 'deno:' + str(deno))
        self.assertEqual(os.environ['PATH'], str(self.system))

    def test_old_system_deno_does_not_hide_compatible_user_install(self):
        self.binary(self.system / 'deno', 'deno 1.46.3')
        deno = self.binary(self.home / '.deno/bin/deno', 'deno 2.3.0')
        self.assertEqual(find_runtime(), 'deno:' + str(deno))

    def test_node_fallback_and_clear_error_for_obsolete_runtime(self):
        self.binary(self.system / 'deno', 'deno 2.2.9')
        node = self.binary(self.system / 'node', 'v20.19.0')
        with self.assertRaisesRegex(ValueError, 'Deno >= 2.3 ou Node >= 22'):
            find_runtime()
        self.binary(node, 'v22.0.0')
        self.assertEqual(find_runtime(), 'node:' + str(node))

    def test_missing_or_unresponsive_runtime_is_reported(self):
        with self.assertRaisesRegex(ValueError, 'runtime JavaScript compatível'):
            find_runtime()
        self.binary(self.system / 'deno', 'deno 2.9.6')
        with patch('gui.js_runtime.subprocess.run', side_effect=subprocess.TimeoutExpired('deno', 2)):
            with self.assertRaisesRegex(ValueError, 'não foi possível executar'):
                find_runtime()

    def test_supported_version_boundaries(self):
        for name, text, valid in [('deno', 'deno 2.3.0', True), ('node', 'v21.9.0', False),
                                  ('quickjs', 'QuickJS version 2023-12-9', True),
                                  ('quickjs', 'QuickJS-ng version 0.12.0', True),
                                  ('bun', '1.3.14', True), ('bun', '1.3.15', False)]:
            with self.subTest(name=name, text=text):
                self.assertEqual(compatible(name, text), valid)


if __name__ == '__main__':
    unittest.main(verbosity=2)
