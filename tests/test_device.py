import unittest

from it9175.device import It9175Device, Link, SimBackend


class SimulatedDeviceTest(unittest.TestCase):
    def setUp(self):
        self.backend = SimBackend()
        self.backend.open()
        self.device = It9175Device(Link(self.backend, lambda msg: None), lambda msg: None)

    def test_init_uploads_firmware_and_loads_scripts(self):
        self.assertTrue(self.device.init())
        self.assertEqual(self.device.chip_id, 0x9175)
        self.assertEqual(self.backend.firmware_bytes, 9036)
        self.assertIn(41, self.backend.commands)
        self.assertIn(35, self.backend.commands)
        self.assertIsNotNone(self.device.tuner)

    def test_tune_locks_and_reports_signal(self):
        self.assertTrue(self.device.init())
        self.assertTrue(self.device.tune(599143))
        status = self.device.status()
        self.assertTrue(status["locked"])
        self.assertEqual(status["raw_strength"], 72)
        self.assertEqual(status["raw_quality"], 80)
        self.assertEqual(status["dbm"], 50)

    def test_ts_reader_returns_aligned_packets(self):
        self.assertTrue(self.device.init())
        data = self.device.read_ts(16356)
        self.assertEqual(len(data) % 188, 0)
        self.assertEqual(data[0], 0x47)

    def test_tune_before_init_fails(self):
        self.assertFalse(self.device.tune(599143))

    def test_simulated_init_without_vendor_image(self):
        """The public snapshot withholds firmware.bin; the fake device must still run."""
        backend = SimBackend()
        backend.open()
        device = It9175Device(Link(backend, lambda msg: None), lambda msg: None,
                              firmware_path="no-such-firmware.bin")
        self.assertTrue(device.init())
        self.assertTrue(device.firmware_simulated)
        self.assertEqual(backend.firmware_bytes, 9036)

    def test_ts_alignment_recovers_from_partial_packet(self):
        packets = b"".join(bytes([0x47]) + bytes([index]) * 187 for index in range(5))
        aligned = self.device._align_ts(b"ABC" + packets)
        self.assertEqual(len(aligned), 5 * 188)
        self.assertEqual(aligned[0], 0x47)
        self.assertEqual(aligned[188], 0x47)

    def test_ts_alignment_carries_remainder(self):
        packet = bytes([0x47]) + bytes(187)
        self.assertEqual(self.device._align_ts(packet[:100]), b"")
        self.assertEqual(len(self.device._align_ts(packet[100:])), 188)


if __name__ == "__main__":
    unittest.main()
