package com.pbcnx.tuner;

/** The only checked exception the door throws: open() failure, permission missing, transport gone. */
public class TunerException extends Exception {

    public TunerException(String message) {
        super(message);
    }

    public TunerException(String message, Throwable cause) {
        super(message, cause);
    }
}
