package com.pbcnx.tuner;

/**
 * The door: one tuner, as the contract's own TUNER-CONTRACT text describes it.
 *
 * <p>This file set is a **draft of the contract artefact**, written to the door's published prose so a driver
 * can compile against it. The door owns the interface: if the published version differs in a signature, this
 * draft is replaced and the driver package recompiled against it - nothing here is upstream of the contract.
 *
 * <p>Lifecycle: {@code open() -> tune(n)* -> close()}, one open per USB instance; a channel change is a tune.
 */
public interface Tuner {

    /** Open the device and bring it up. The only method that throws. */
    void open() throws TunerException;

    /** Tune and return the verdict: true = locked, false = no lock (an I/O failure is a closed handle). */
    boolean tune(int frequencyKhz);

    /** Change channel on the live handle: stop the reader, tune, wait for lock, re-arm the reader. */
    boolean zap(int frequencyKhz);

    /** A snapshot; never throws. Unread fields are -1. */
    TunerStatus status();

    /** One TMCC read: null, or a record whose {@link Tmcc#valid()} is false. For humans use tmccSettled. */
    Tmcc tmcc();

    /** Two agreeing valid reads, bounded attempts; null when it never settles. */
    Tmcc tmccSettled(int attempts, long delayMs);

    /** The four-state ladder, in place: state 3 is recovered without an upload; a blank chip may be rebuilt. */
    boolean recover();

    /** Tear the transport down, keep the state (a detach). */
    void suspend();

    /** Rebuild on the new handle (an attach). May run a recovery when the warm tune does not lock. */
    boolean resume(android.hardware.usb.UsbDevice device) throws TunerException;

    /** Sweep a range on a worker; the verdict is the stream, not the lock word. */
    void scan(int startKhz, int stopKhz, int stepKhz, int seconds, ScanListener listener);

    /** Optional: only a package that cannot stream when {@code open()} returns needs it. */
    default void start() {
    }

    /** Stop the reader, close the transport. Safe twice. */
    void close();
}
