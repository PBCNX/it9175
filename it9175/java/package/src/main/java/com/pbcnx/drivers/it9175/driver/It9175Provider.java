package com.pbcnx.drivers.it9175.driver;

import android.content.Context;
import android.hardware.usb.UsbDevice;

import com.pbcnx.tuner.Tuner;
import com.pbcnx.tuner.TunerProvider;
import com.pbcnx.tuner.TsReader;

/**
 * The door's entry point for this driver.
 *
 * <p>Four construction arguments, no singleton: the firmware image is the host's (this package does not ship
 * vendor firmware), the listener is the host's sink, and the device is the instance the host just got a grant
 * for.
 */
public final class It9175Provider implements TunerProvider {

    /** The USB ids this package answers for: GMA NOW / ITE IT9175. */
    public static final int VENDOR_ID = 0x048d;
    public static final int PRODUCT_ID = 0x275a;

    /** True when {@code device} is this driver's chip - for a host's device list, no Android runtime needed. */
    public static boolean isSupported(UsbDevice device) {
        return device != null
                && device.getVendorId() == VENDOR_ID
                && device.getProductId() == PRODUCT_ID;
    }

    @Override
    public Tuner open(Context context, UsbDevice device, byte[] firmware, TsReader.Listener listener) {
        return new It9175Tuner(context, device, firmware, listener);
    }
}
