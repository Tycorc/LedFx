# Disco

## Overview

Disco is sound to light for a room of smart bulbs, modelled on the Disco mode of Hue apps such as hueDynamic. It is built for a [Philips Hue entertainment zone](../../devices/hue.md), a room of LIFX bulbs or a few Nanoleaf panels, where every pixel is a whole lamp. On a strip or matrix the output is split into zones instead.

Where the [Rave](rave.md) and [Light Show](light_show.md) effects step through patterns on the beat, Disco listens to the music itself. It has three analysers that correspond to the Spectrum, Peak and Neural tabs of the hueDynamic app.

## Modes

### Spectrum

Three channels, **bass**, **voice** and **treble**, each listen to their own frequency band (40 to 180 Hz, 220 Hz to 2 kHz and 3 to 12 kHz by default). Each channel owns some of the lamps. Whenever a band peaks, its lamps flash with a new colour from the palette, so the bass lamps thump with the kick, the voice lamps follow the vocal and the treble lamps twinkle with the hi-hats.

Which lamps belong to which channel is the **Assignment**:

| Assignment    | Lamps                                                                          |
|---------------|--------------------------------------------------------------------------------|
| `Interleaved` | Bass, voice, treble, bass, voice, treble... along the light order.             |
| `Blocks`      | The first third of the lamps are bass, the middle third voice, the last treble.|
| `All lights`  | Every lamp shows whichever channel is loudest right now.                       |

Channels can be switched off with the **Bass**, **Voice** and **Treble** toggles, and the remaining channels share the lamps. For full control there is the **Light Map** in the advanced settings: a string with one letter per lamp, `B` for bass, `V` for voice, `T` for treble and `-` for a lamp that stays off, for example `BVTBV` for five lamps. A shorter map repeats.

### Peak

A single channel on the beat. Every hit pulses all lamps together with a new palette colour. This is the mode for a clear, whole room pulse. **Idle Brightness** keeps the lamps glowing between hits, and **Strobe** flashes the strobe colour for a split second at the start of every hit before the colour comes through.

### Neural

No hits at all. The colour follows where the energy sits in the spectrum: bass heavy passages sit at the start of the palette, bright passages at the end, and the lamps spread out a little on either side of that point so the room shows related colours rather than one. Brightness follows loudness, and with **Modulate Saturation** on, transients wash the colour towards white for a moment. This is the mode for a lounge or a chill playlist.

## Settings

### Sensitivity

How easily the lights react. It raises the audio gain and lowers the threshold a channel needs to jump above its own running average to count as a hit. Turn it up for quiet sources and down if everything triggers on every frame.

### Smoothness

How sluggish the lights are. Higher values smooth the band levels before the detectors see them and lengthen the pulses. `0` reacts to everything, `1` glides.

### Intensity

How hard the lamps react, from a gentle pulse at low values to full flashes at `1`.

### Idle Brightness

Brightness of the lamps between hits, so the room is never completely dark.

### Fade And Fast Pulse

With **Fade** on, a hit lights the lamps and they fade back out. **Fast Pulse** makes that a short, sharp pulse of about a tenth of a second, off gives a slower decay of just under half a second. Smoothness lengthens both.

With **Fade** off the lamps do not pulse at all but follow the loudness of their band, like a VU meter per channel, and still take a new colour on every hit.

### Palette

The palette is the normal LedFx gradient picker and plays the role of the hue range sliders in the app: every hit picks a new colour from it, at least 15% further along than the last one so every hit is a visible change. A palette with a single colour gives single colour pulses.

In Spectrum mode **Channel Colors** decides how the three channels share it. `Palette thirds` (the default) gives the bass channel the first third of the palette, voice the middle and treble the last third, so with a rainbow palette the bass lamps stay in the reds and oranges and the treble lamps in the blues and pinks, and you can tell the channels apart at a glance. `Whole palette` lets every channel roam the full palette, which is how the app behaves with all three hue ranges set wide.

Saved gradients and the Now Playing album art gradient apply to Disco like any other gradient effect. The album art gradient also sets the strobe colour to the palette's end colour.

## Advanced Controls

### Band Edges

`Bass Low` / `Bass High`, `Voice Low` / `Voice High` and `Treble Low` / `Treble High` set the frequency bands of the three channels in Hz. The Peak mode uses the bass band.

### Zones

How many lamps the output is split into. `0` is automatic: one zone per pixel for up to 32 pixels, 8 zones for anything larger.

### Strobe Color

The colour flashed by the Peak strobe.

```{warning}
Flashing lights, and in particular whole room flashes faster than about three per second, can trigger seizures in people with photosensitive epilepsy. Check who is in the room before using the strobe or a high sensitivity.
```

## Presets

| Preset          | Mode     | Notes                                                        |
|-----------------|----------|--------------------------------------------------------------|
| Spectrum Party  | Spectrum | All three channels interleaved, fast pulses, rainbow palette |
| Bass And Treble | Spectrum | Voice channel off, red / pink / blue palette                 |
| Peak Pulse      | Peak     | Slow pulses with a 15% idle glow                             |
| Peak Strobe     | Peak     | White strobe flash on every beat, cyan to pink               |
| Neural Lounge   | Neural   | Smooth, 20% idle glow, warm to cool palette                  |

## Tips For Smart Bulbs

Smart bulbs are slow. A Hue entertainment zone is streamed at 30 frames per second, the bridge passes on at most 25 updates per second and Philips recommends effects change no faster than about 12 times per second. Disco never fires a channel more than about eight times per second for that reason. If the bulbs still look smeared, raise Smoothness or turn Fast Pulse off.
