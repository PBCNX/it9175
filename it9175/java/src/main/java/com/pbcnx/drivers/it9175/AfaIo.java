/*
 * Ported from OpenDTV (https://github.com/jpdcs/OpenDTV), MIT.
 * Copyright (c) 2026 jpdcs. The MIT permission notice is in NOTICE and LICENSE.
 */
package com.pbcnx.drivers.it9175;

/** {@link Io} over the USB command transport. */
public final class AfaIo implements Io {
    private final Transport transport;
    private int sequence;

    public AfaIo(Transport transport) {
        this.transport = transport;
    }

    private int nextSequence() {
        int value = sequence;
        sequence = (sequence + 1) & 0xFF;
        return value;
    }

    /**
     * One request/response pair on the command endpoint. Serialised on this
     * object: the command link has exactly one conversation at a time even if a
     * host calls {@code status()}, {@code tune()} and the firmware upload from
     * different threads. Without this, a status read already on the wire when a
     * tune starts interleaves frames and desynchronises the chip's sequence -
     * measured on the Android TV box 2026-11-17, where the endpoint then answered -1 to
     * every command until the driver recovered.
     *
     * <p>A host that adds a 1 Hz poller around a link designed for one caller
     * (the IT9175 app did) is safe with this lock. The stronger 9308 shape - a
     * single thread that owns the transport and a queue in front of it - is a
     * later refinement, not a requirement for correctness.</p>
     */
    private synchronized byte[] exchange(byte[] frame, int expected) {
        try {
            transport.write(frame, 1000);
            byte[] response = transport.read(256, 1000);
            return AfaCmd.parseResponse(response, expected);
        } catch (RuntimeException error) {
            return null;
        }
    }

    public byte[] read(int processor, long address, int count) {
        return exchange(AfaCmd.buildRead(nextSequence(), processor, address, count), count);
    }

    public boolean write(int processor, long address, byte[] data) {
        return exchange(AfaCmd.buildWrite(nextSequence(), processor, address, data), 0) != null;
    }

    public byte[] command(int command, int processor, byte[] payload, int expected) {
        return exchange(AfaCmd.buildCommand(command, nextSequence(), 0, processor, payload), expected);
    }

    public void sleep(int millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
        }
    }

    public byte[] firmwareVersion(int processor) {
        return exchange(AfaCmd.buildCommand(34, nextSequence(), 0, processor, new byte[]{1}), 4);
    }
}
