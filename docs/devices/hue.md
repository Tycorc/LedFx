# Philips Hue Device

LedFx drives **Philips Hue** lights through the Hue **Entertainment API**. Rather than sending one REST call per bulb, it opens an encrypted UDP stream (DTLS) to the bridge and pushes a colour for every light in an entertainment zone at 30 frames per second. This is the same low latency path that the Hue Sync box and the Hue app's own entertainment features use, and it is what makes beat synced effects across a room of bulbs possible.

Each light in the entertainment zone becomes one pixel of the LedFx device, in the order the Hue app lists them in the zone. A zone with five bulbs is a five pixel device.

## Requirements

- A Hue Bridge v2 (the square one) on recent firmware. LedFx checks the firmware version when the device is added and tells you to update through the Hue app if it is too old.
- An **entertainment area** created in the Hue app that contains the lights you want to use. The Hue app only lets you add lights that support entertainment streaming.
- At most 20 channels in the zone. The Hue app itself limits an entertainment area to 10 lights, and gradient products such as the Play gradient strip use several channels each.
- The optional `python-mbedtls` package, which provides the DTLS encryption for the stream.

### Installing the Hue extra

The Windows and macOS release builds ship with Hue support included.

For pip and uv installs, add the `hue` extra:

```console
pip install "ledfx[hue]"
```

```{note}
`python-mbedtls` currently only publishes wheels for Python 3.10 to 3.12 on x86 Linux, Windows and macOS. On Python 3.13, and on ARM Linux such as a Raspberry Pi, the Hue device will not load and LedFx will report that `python-mbedtls` needs to be installed.
```

## Setup

1. In the Hue app, create an entertainment area (Settings, Entertainment areas) with the lights you want, and note its name.
2. In LedFx, add a device of type **Hue** and fill in:
   - **IP address**: the address of the Hue bridge.
   - **Group name**: the name of the entertainment area, exactly as in the Hue app. It is not case sensitive.
   - **UDP port**: leave at `2100` unless you know your bridge is different.
3. Press the physical **link button** on the bridge, then press **Add** in LedFx within about 30 seconds. LedFx registers itself with the bridge and stores the credentials in its config, so the button only needs pressing once.

If you see *You need to press the Bridge Link Button and retry* the button was not pressed in time. Press it and add the device again.

If the bridge later forgets the registration, LedFx clears the stored credentials and asks you to press the link button and restart LedFx.

## Using the device

While the LedFx device is active the entertainment zone is in streaming mode. The Hue app shows this and will not let you control those lights from its own scenes until LedFx releases them, which happens when the virtual is turned off or LedFx exits.

Any LedFx effect can be set on a Hue device, but bear in mind that the device only has as many pixels as it has lights. Effects that draw shapes along a strip, such as scans, equalizers or text, do not have enough pixels to work with and degrade into flicker. Effects that change the whole output at once, or that treat each pixel as an independent lamp, look great.

### Party mode

For a party or rave mode across the room, use the **Rave** effect. It was built for exactly this case: each bulb is a zone, and the zones snap to new palette colours on the beat, with random, wash, chase, alternate and strobe patterns. The built in presets *Club*, *Rainbow Party*, *Strobe Drop*, *Police*, *Round The Room* and *Slow Wash* are good starting points. See the [Rave effect documentation](../effects/simple/rave.md) for all the settings and for tips on bulb friendly step rates.

Other effects that work well on a handful of bulbs are **BPM Strobe**, **Bar**, **Multicolor Bar**, **Power**, **Energy** and **Blade Power+**, all of which colour the whole output from the music.

## Limits and tips

- The bridge relays at most 25 updates per second to the lights over Zigbee, and Philips recommends that effects change no faster than about 12 times per second. Bulbs visibly lag behind anything quicker, so pick effect settings that step at beat rate rather than frame rate.
- Keep the bridge on Ethernet and, if possible, the LedFx host as well. The stream is UDP and does not recover lost packets.
- Only one application can stream to an entertainment area at a time. Stop the Hue app's own entertainment sessions, the Hue Sync desktop app or a Hue Sync box before activating the LedFx device, or the stream will fail to start.
- If the stream cannot be established LedFx logs *Could not connect to the Bridge* and suggests power cycling the bridge, which clears a stuck streaming session.
