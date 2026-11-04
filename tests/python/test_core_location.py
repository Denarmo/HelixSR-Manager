"""The Linux edition uses a network built in the shared data folder (by the Decky plugin or the Flutter app)."""

import importlib.util
import os
import shutil
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENGINE = os.path.join(REPO, "src", "linux", "helixsr_swapper_linux.py")


def load_engine():
    spec = importlib.util.spec_from_file_location("helixsr_engine_core_location", ENGINE)
    eng = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(eng)
    return eng


def make_core(d, network):
    os.makedirs(d, exist_ok=True)
    body = b"MZ\0HelixSR 1.8.1\0" + b"\0" * 64
    if network:
        body += b"\x01" * 30 + b"HXSRNET1" + (10).to_bytes(8, "little") + (20).to_bytes(8, "little") + bytes(8)
    with open(os.path.join(d, "amd_fidelityfx_dx12.dll"), "wb") as f:
        f.write(body)


class CoreLocationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="helixsr-core-")
        self.old_env = dict(os.environ)
        os.environ["XDG_DATA_HOME"] = os.path.join(self.tmp, "data")
        self.shared = os.path.join(self.tmp, "data", "HelixSR", "core", "HelixSR-1.8.1")

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.old_env)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_bundled_core_without_shared_network(self):
        eng = load_engine()
        self.assertNotEqual(eng.CORE_DIR, self.shared)
        self.assertEqual(eng.shared_core_dir(), self.shared)

    def test_shared_network_is_used_when_bundled_is_not_built(self):
        make_core(self.shared, network=True)
        eng = load_engine()
        self.assertFalse(eng.network_built(os.path.join(REPO, "helixsr_core", "HelixSR-1.8.1")))
        self.assertEqual(eng.CORE_DIR, self.shared)
        self.assertTrue(eng.get_core_status()["weightsBuilt"])

    def test_unbuilt_shared_core_is_ignored(self):
        make_core(self.shared, network=False)
        eng = load_engine()
        self.assertNotEqual(eng.CORE_DIR, self.shared)

    def test_built_bundled_core_wins(self):
        bundled = os.path.join(self.tmp, "app", "helixsr_core", "HelixSR-1.8.1")
        make_core(bundled, network=True)
        make_core(self.shared, network=True)
        eng = load_engine()
        self.assertEqual(eng.prefer_built_core(bundled), bundled)


if __name__ == "__main__":
    unittest.main()
