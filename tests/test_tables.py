import os
import unittest

from it9175 import firmware, tables

FIRMWARE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "it9175", "firmware.bin")


class TablesTest(unittest.TestCase):
    def test_script_arrays_present(self):
        for name in ("INIT_A0", "INIT_A1", "INIT_B0", "INIT_B1", "TUNE_PRE0", "TUNE_PRE1"):
            ops = getattr(tables, name)
            self.assertGreaterEqual(len(ops), 6, name)
            for op in ops:
                self.assertIn(op[0], "IMPQVW", name)
                self.assertIn(op[1], "08", name)

    def test_band_tables(self):
        for name in ("BANDS0", "BANDS1"):
            rows = getattr(tables, name)
            self.assertGreater(len(rows), 4, name)
            for row in rows:
                self.assertEqual(len(row), 8, name)
                self.assertTrue(all(0 <= value <= 0xFFFFFFFF for value in row))

    @unittest.skipUnless(os.path.exists(FIRMWARE), "vendor firmware image not present")
    def test_firmware_matches_documented_hash(self):
        image = firmware.image()
        self.assertEqual(len(image), 9036)
        self.assertEqual(len(firmware.CHUNKS), 189)
        self.assertEqual(sum(firmware.CHUNKS), len(image))
        self.assertEqual(firmware.SHA256,
                         "451b09a40d072d3e7c0b805f3d180a8c8e10456a3768cce0cc27510c05c3575c")


    def test_missing_firmware_is_reported(self):
        with self.assertRaises(FileNotFoundError):
            firmware.image(os.path.join(os.path.dirname(FIRMWARE), "does-not-exist.bin"))


if __name__ == "__main__":
    unittest.main()
