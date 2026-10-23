import unittest

from it9175.device import (EP_CMD_IN, EP_CMD_OUT, EP_TS_IN, UsbBackend)


class FakeEndpoint:
    def __init__(self, address):
        self.bEndpointAddress = address


class FakeInterface:
    def __init__(self, number, endpoints):
        self.bInterfaceNumber = number
        self._endpoints = [FakeEndpoint(e) for e in endpoints]

    def __iter__(self):
        return iter(self._endpoints)


class FakeConfig:
    def __init__(self, interfaces):
        self._interfaces = interfaces

    def __iter__(self):
        return iter(self._interfaces)


class FakeDevice:
    def __init__(self):
        self.idProduct = 0x275A
        self.bus = 1
        self.address = 4
        self.claimed = []
        self.config = FakeConfig([FakeInterface(0, [EP_CMD_IN, EP_CMD_OUT, EP_TS_IN])])

    def __iter__(self):
        return iter([self.config])

    def is_kernel_driver_active(self, number):
        return False

    def claim_interface(self, number):
        self.claimed.append(number)

    def release_interface(self, number):
        self.claimed.remove(number)

    def set_configuration(self):
        pass


class UsbBackendTest(unittest.TestCase):
    def test_endpoint_discovery_and_claim(self):
        dev = FakeDevice()
        backend = UsbBackend(dev).open()
        self.assertEqual(dev.claimed, [0])
        self.assertIn("048d:275a", backend.description)
        self.assertIn("IT9175", backend.description)
        backend.close()
        self.assertEqual(dev.claimed, [])

    def test_missing_endpoint_is_reported(self):
        dev = FakeDevice()
        dev.config = FakeConfig([FakeInterface(0, [EP_CMD_IN, EP_CMD_OUT])])
        with self.assertRaises(Exception) as ctx:
            UsbBackend(dev).open()
        self.assertIn("0x84", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
