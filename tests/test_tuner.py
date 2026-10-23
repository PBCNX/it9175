import unittest

from it9175.device import It9175Device, Link, SimBackend


class TunerMathTest(unittest.TestCase):
    """Golden values produced by OpenDTV's Java It9175Tuner (see tools/java_math_check.py)."""

    @classmethod
    def setUpClass(cls):
        backend = SimBackend()
        backend.open()
        cls.device = It9175Device(Link(backend, lambda m: None), lambda m: None)
        assert cls.device.init()

    def test_thresholds(self):
        self.assertEqual(self.device.tuner.thr,
                         [53000, 96708, 128944, 193416, 257888, 386833, 515777, 193416, 950000])

    def test_frequency_words_match_java(self):
        expected = {
            473143: (5, 8, 5678, 46638, 46674),
            497143: (5, 8, 5966, 46926, 46962),
            599143: (7, 4, 3595, 60939, 60957),
            671143: (7, 4, 4027, 61371, 61389),
            695143: (7, 4, 4171, 61515, 61533),
        }
        for freq, (nc, nv, fcw, lo, iq) in expected.items():
            self.assertEqual(self.device.tuner.freq_code(freq), (nc, nv, fcw), freq)
            self.assertEqual(self.device.tuner.lo_freq(freq), lo, freq)
            self.assertEqual(self.device.tuner.cal_freq_iqik(freq, 16), iq, freq)

    def test_band_selection_is_monotonic(self):
        previous = -1
        for freq in range(473143, 695144, 6000):
            nc = self.device.tuner.get_nc(freq)
            self.assertGreaterEqual(nc, previous)
            previous = nc


if __name__ == "__main__":
    unittest.main()
