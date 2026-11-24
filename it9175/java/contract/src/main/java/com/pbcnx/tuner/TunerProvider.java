package com.pbcnx.tuner;

import android.content.Context;
import android.hardware.usb.UsbDevice;

/**
 * How a host gets a {@link Tuner}: four construction arguments, never a singleton or a hidden global.
 *
 * <p>The firmware image is an argument because a driver does not ship vendor firmware in a package.
 */
public interface TunerProvider {

    Tuner open(Context context, UsbDevice device, byte[] firmware, TsReader.Listener listener);
}
