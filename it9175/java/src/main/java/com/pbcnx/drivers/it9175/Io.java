/*
 * Ported from OpenDTV (https://github.com/jpdcs/OpenDTV), MIT.
 * Copyright (c) 2026 jpdcs. The MIT permission notice is in NOTICE and LICENSE.
 */
package com.pbcnx.drivers.it9175;

/** Register access used by the tuner. Returns null when a read fails. */
public interface Io {
    byte[] read(int processor, long address, int count);

    boolean write(int processor, long address, byte[] data);

    void sleep(int millis);

    byte[] firmwareVersion(int processor);
}
