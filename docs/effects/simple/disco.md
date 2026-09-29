# Disco

## Overview

Disco is sound to light for a room of smart bulbs. It is built for a [Philips Hue entertainment zone](../../devices/hue.md), a room of LIFX bulbs or a few Nanoleaf panels, where every pixel is a whole lamp. On a strip or matrix the output is split into zones instead.

Where the [Rave](rave.md), [Light Show](light_show.md) and [Party](party.md) effects step through patterns on the beat, Disco listens to the music itself: each channel decides for itself when the music hits, flashes its lamps, and lets them fade until the next beat. Between songs the lamps never go dark but drift through slowly changing colours.

## Modes

### Spectrum

Three channels, **bass**, **voice** and **treble**, each listen to their own frequency band (40 to 180 Hz, 220 Hz to 2 kHz and 3 to 12 kHz by default). Each channel owns some of the lamps. Whenever a band hits, its lamps flash a new palette colour and then, depending on the channel's **style**, fade down until the next beat is due, or hold the colour. The bass lamps thump with the kick, the voice lamps follow the vocal and the treble lamps twinkle with the hi-hats.

Which lamps belong to which channel is the **Assignment**:

| Assignment    | Lamps                                                                          |
|---------------|--------------------------------------------------------------------------------|
| `Interleaved` | Bass, voice, treble, bass, voice, treble... along the light order.             |
| `Blocks`      | The first third of the lamps are bass, the middle third voice, the last treble.|
| `All lights`  | Every lamp flashes on every channel's hits.                                    |

Channels can be switched off with the **Bass**, **Voice** and **Treble** toggles, and the remaining channels share the lamps. For full control there is the **Light Map** in the advanced settings: a string with one letter per lamp, `B` for bass, `V` for voice, `T` for treble and `-` for a lamp that stays off, for example `BVTBV` for five lamps. A shorter map repeats.

Every channel has a **style**:

| Style          | After a hit                                                                      |
|----------------|----------------------------------------------------------------------------------|
| `Fade`         | Full brightness, then a straight fade down to the **Fade Brightness**, timed to land just as the next beat is due (the fade lasts as long as the gap since the previous hit, up to 1.4 s). |
| `Fade + pulse` | The same, but every **Pulse Block** hits the channel switches between those beat length fades and short 200 ms pulses, so the feel changes every couple of bars. |
| `Hold`         | Full brightness until the next hit changes the colour.                           |

The defaults, bass `Fade + pulse`, voice `Hold`, treble `Fade`, give a pulsing bass, a steady vocal colour and a sparkling top end.

### Peak

A single channel on the overall loudness. Every hit flashes **one random lamp** with a new palette colour, so the room sparkles beat by beat. **Link Lights** flashes every lamp together instead, for a whole room pulse. **Fade** and **Fast Pulse** set the style of that channel, and **Strobe** turns every hit into a flash of the strobe colour followed by dark.

### Void

No hits at all. The colour follows the loudest part of the spectrum below 2 kHz, low notes at the start of the palette and high notes at the end, smoothed so it glides rather than jumps. Brightness follows the loudness relative to the last couple of seconds, so a build gets brighter and a breakdown dims. With **Modulate Saturation** on, quiet passages go pale and loud ones vivid. All lamps show the same colour. Named after the film whose colour trips it was tuned to feel like: put a long palette on it and let it run.

## Settings

### Sensitivity

How easily a channel hits. A hit needs the band to jump clearly above its own running average of the last couple of seconds; sensitivity is a gain on the band from 0.4× to 1.6×, so at `0.5` a hit needs about one and a half times the average, at `1` about the average, and at `0` nearly four times it.

### Smoothness

Lengthens every fade by up to half a second above `0.5`, or shortens it below. In Void mode it sets how many frames the colour and brightness are averaged over.

### Intensity

Overall brightness of the show.

### Fade Brightness

The brightness a fade ends on. `0.16` is a normal party mood: the lamps dip low between beats. `0.69` is a relaxed mood where the lamps stay bright and only dip a little.

### Idle Brightness

After two seconds without a hit a channel's lamps start to drift: every two seconds each lamp picks a new random palette colour and glides to it at this brightness. `1.0` is the party default, the relaxed presets use `0.69`, and `0` lets the room go dark between songs.

### Strobe

In Peak mode every hit becomes a 100 ms flash of the **Strobe Color** followed by dark, at most five per second. In Spectrum mode the strobe fires only when the bass and treble channels hit in the same instant, which flashes every lamp, so it marks the big accents of a track rather than every beat.

### Palette

The palette is the normal LedFx gradient picker. Every hit picks a new colour from it, at least 15% further along than the last one so every hit is a visible change. In Spectrum mode **Channel Colors** decides how the three channels share it: `Palette thirds` (the default) gives bass the first third, voice the middle and treble the last third, so the channels can be told apart at a glance; `Whole palette` lets every channel roam. Saved gradients and the Now Playing album art gradient apply like on any gradient effect.

## Advanced Controls

- **Band edges**: `Bass Low` / `Bass High`, `Voice Low` / `Voice High` and `Treble Low` / `Treble High` in Hz.
- **Gate Decay**: after a hit, a new hit must be louder than the previous one as that memory fades to nothing over this many seconds. Short values (0.5 s) let busy drum and bass through, long ones (3 to 5 s) calm ambient and classical down to the real accents.
- **Pulse Block**: how many hits a channel plays in each block before `Fade + pulse` switches between fades and pulses.
- **Zones**: how many lamps the output is split into. `0` is automatic: one per pixel for up to 32 pixels, 8 zones for anything larger.
- **Strobe Color**: the colour of the strobe flash.

```{warning}
Flashing lights, and in particular whole room flashes faster than about three per second, can trigger seizures in people with photosensitive epilepsy. Check who is in the room before using the strobe or a high sensitivity.
```

## Presets

The Spectrum presets are tuned per genre: band edges that suit the music, a palette where each channel has its own colour family, and a gate decay that matches how busy the music is. The relaxed ones (R&B, Classical, Jazz, Acoustic, Ambient) keep the lamps bright between beats.

| Preset        | Feel                                                        |
|---------------|-------------------------------------------------------------|
| Pop           | Pink bass, red to yellow vocals, green top end              |
| Rock          | Magenta bass pulses, orange vocals, warm treble             |
| Hip Hop       | Red bass pulses, orange vocals, blue treble, slow gate      |
| R&B           | Relaxed, magenta and blue, long fades                       |
| Dance         | Magenta bass pulses, yellow and green vocals, blue treble   |
| Classical     | Relaxed, blues and violets, very slow gate                  |
| Jazz          | Relaxed, orange bass, magenta vocals, blue treble           |
| Acoustic      | Relaxed, red bass, yellow vocals, blue treble               |
| Drum And Bass | Fast gate, four hit blocks, strobe on bass and treble hits  |
| Trance        | Fast gate, four hit blocks, strobe, pulsing bass and treble |
| Ambient       | Relaxed, teal and blue, the slowest gate                    |
| Peak Pulse    | One random lamp per beat, rainbow                           |
| Peak Linked   | Every lamp per beat, cyan to pink, fast pulses              |
| Peak Strobe   | White strobe on every beat                                  |
| Enter The Void| The Void analyser on a green to red palette                 |

## Tips For Smart Bulbs

Smart bulbs are slow. A Hue entertainment zone is streamed at 30 frames per second, the bridge passes on at most 25 updates per second and Philips recommends effects change no faster than about 12 times per second. Disco never hits a channel more than ten times per second and never strobes faster than five, for that reason. If the bulbs still look smeared, raise Smoothness or set the busy channel to `Fade`.
