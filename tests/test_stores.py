"""Run: python3 -m unittest discover -s tests"""

import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))

from gameyfin.installed import InstalledStore  # noqa: E402
from gameyfin.settings import Settings, SettingsStore  # noqa: E402


class StoreTests(unittest.TestCase):
    def test_concurrent_puts_keep_every_record(self):
        with tempfile.TemporaryDirectory() as d:
            store = InstalledStore(d)
            threads = [threading.Thread(target=store.put, args=(str(i), {"title": f"G{i}"})) for i in range(20)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(len(store.load()), 20)

    def test_corrupt_settings_load_as_empty(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "settings.json"), "w") as f:
                f.write("{not json")
            self.assertEqual(SettingsStore(d).load(), Settings())
            with open(os.path.join(d, "settings.json"), "w") as f:
                f.write("[]")
            self.assertEqual(SettingsStore(d).load(), Settings())


if __name__ == "__main__":
    unittest.main()
