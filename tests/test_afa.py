import unittest

from it9175 import afa


class AfaFramingTest(unittest.TestCase):
    def test_read_frame_is_byte_exact(self):
        frame = afa.build_read(0, 0, 0, 0x1222, 1)
        self.assertEqual(frame, bytes.fromhex("0b0000000102000012 22db ec".replace(" ", "")))

    def test_write_frame_is_byte_exact(self):
        frame = afa.build_write(0, 0, 8, 0xEC4C, b"\xa8")
        self.assertEqual(frame, bytes.fromhex("0c80010001020000ec4ca83069"))

    def test_command_frame_is_byte_exact(self):
        frame = afa.build_command(34, 0, 0, 0, b"\x01")
        self.assertEqual(frame, bytes.fromhex("0600220001ffdc"))

    def test_checksum_roundtrip(self):
        for seq in (0, 1, 255):
            for addr in (0, 0x4C, 0x1222, 0xEC4C):
                for proc in (0, 8):
                    frame = afa.build_read(seq, 0, proc, addr, 1)
                    self.assertEqual(frame[-2] << 8 | frame[-1], afa.checksum(frame, len(frame) - 2))
                    self.assertEqual(frame[0], len(frame) - 1)

    def test_parse_response(self):
        body = bytes([0x75])
        frame = bytearray(5 + len(body))
        frame[0] = len(frame) - 1
        frame[2] = 0
        frame[3:3 + len(body)] = body
        cs = afa.checksum(frame, len(frame) - 2)
        frame[-2], frame[-1] = cs >> 8, cs & 0xFF
        self.assertEqual(afa.parse_response(bytes(frame), 1), body)
        self.assertIsNone(afa.parse_response(bytes(frame), 2))
        frame[2] = 7
        self.assertIsNone(afa.parse_response(bytes(frame), 1))


if __name__ == "__main__":
    unittest.main()
