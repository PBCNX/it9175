/*
 * Ported from OpenDTV (https://github.com/jpdcs/OpenDTV), MIT.
 * Copyright (c) 2026 jpdcs. The MIT permission notice is in NOTICE and LICENSE.
 */
package com.pbcnx.drivers.it9175;

/** Byte transport implemented by the host (Android UsbDeviceConnection, tests, ...). */
public interface Transport {
    void write(byte[] data, int timeoutMs);

    byte[] read(int maxLength, int timeoutMs);
}
