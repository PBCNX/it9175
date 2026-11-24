"""The attach supervisor: rebuild a session when the dongle goes away and comes back.

The vendor app's pattern (from its decompiled sources): a USB detach tears the TV path down and an
attach rebuilds it, restoring the channel from cache. It never tries to revive the old handle - that is
why a quick replug looks seamless. This module is the driver-side equivalent for `play`.

Kept separate from the CLI so it can be tested without hardware: the only thing it knows is a callable
that returns a fresh, working session (or raises / returns None).
"""
import time


def wait_for_device(open_fn, attempts=60, delay_s=0.5, sleep=None, log=None):
    """Call ``open_fn`` until it returns something truthy, then return it.

    ``open_fn`` is expected to raise when the device is absent (no matching USB id) or when a
    bring-up fails; both cases are treated as "not yet" and retried. ``attempts`` bounds the wait;
    returns None when the budget is spent, so the caller can fall back to a human.
    """
    sleep = sleep or time.sleep
    for attempt in range(attempts):
        sleep(delay_s)
        try:
            session = open_fn()
        except Exception as error:          # absent, or came back but would not bring up
            if log is not None:
                log("waiting (%d/%d): %s" % (attempt + 1, attempts, error))
            continue
        if session:
            if attempt and log is not None:
                log("device back after %d attempt(s)" % (attempt + 1))
            return session
    return None
