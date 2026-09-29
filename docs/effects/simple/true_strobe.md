# True Strobe

## Overview

True Strobe is a real, hard strobe for a room of smart bulbs: every lamp that takes part in a flash switches on in the same frame and off again in the same frame, so bulbs, gradient strip segments and WLED strips flash in perfect sync. It runs at a set rate rather than on a beat fraction, which is what makes it feel like a strobe rather than a light show, and it uses the [room positions](../../devices/hue.md#room-positions) of the lamps for its spreads: alternating groups, turning halves, corners, a sweep round the room, rings from the centre, scatters.

```{warning}
This effect flashes the whole room up to 12 times a second. Flashing lights, and in particular whole room flashes faster than about three per second, can trigger seizures in people with photosensitive epilepsy. Unlike [Party](party.md) and [Light Show](light_show.md) there is no flash limiter here, the rate is the point. Know who is in the room before you use it, and keep the rate down or use beat bursts when in doubt.
```

## How It Works

The flashes run on a fixed clock: at a **Rate** of 8 there is a flash every 125 ms, and each flash stays lit for **On Time** seconds (50 ms by default), then the lamps go dark until the next one. The timing is taken from the render clock, not from the frame count, so at 30 frames per second an 8 Hz strobe still gives clean on and off frames, and a flash shorter than a frame is held until it has been rendered once so that no flash is ever lost. On Time is never more than half the time between two flashes, so there is always a dark gap at least as long as the flash.

The **Spread** decides which lamps take part in each flash, the **Color Mode** what colour they flash, and the **Gate** when the strobe runs at all.

## Spreads

| Spread      | Which lamps flash                                                                                      |
|-------------|--------------------------------------------------------------------------------------------------------|
| `all`       | Every lamp, all in sync. The classic strobe.                                                           |
| `alternate` | Two interleaved groups by angle around the room take turns, so neighbouring lamps flash on alternate flashes. |
| `halves`    | Front half, back half, right half, left half: the dividing line turns 90 degrees every second flash. |
| `corners`   | The next of **Sectors** balanced channels around the room on each flash (4 sectors are the four corners). |
| `sweep`     | The next angular sector on each flash, going clockwise round the room.                                |
| `ripple`    | Rings from the centre of the room outwards, **Sectors** rings.                                         |
| `scatter`   | A random **Density** fraction of the lamps on every flash, all switching together.                     |
| `random`    | One random lamp per flash, never the same lamp twice running.                                          |

The groups are balanced, so a room with all its lamps on one side still fills every corner and sector, and a spread never produces an empty flash.

## Color Modes

| Mode                   | Colours                                                                               |
|------------------------|---------------------------------------------------------------------------------------|
| `strobe color`         | Every flash is the **Strobe Color** (white by default).                               |
| `palette cycle`        | Every flash moves **Color Step** along the palette, so the colour changes flash by flash. |
| `palette by position`  | Each lamp keeps its own palette colour by its angle around the room: a rainbow in 3D that strobes. |
| `palette random`       | Every lamp gets a random palette colour on every flash.                               |

## Gates

| Gate          | When the strobe runs                                                                             |
|---------------|--------------------------------------------------------------------------------------------------|
| `always`      | Continuously.                                                                                    |
| `beat bursts` | **Burst Flashes** flashes after every step, then dark until the next step. Steps come from the [trigger](rave.md#trigger) settings: the beat, bass hits, onsets or a timer. |
| `level`       | Only while the level of the **Band** is above the **Threshold**, so the bass opens the strobe.   |

With `beat bursts`, a burst that is still running when the next step comes is cut and the new burst starts, so the strobe never drifts away from the beat.

## Tail And Background

- **Tail**: how much of the gap to the next flash the light fades out over. `0` is a hard off, `1` fades all the way to the next flash. With beat bursts the last flash of a burst fades over the rest of the step, which gives the three strobes and a fade look.
- **Background**: brightness of the lamp colours between the flashes. At `0` the lamps are black between flashes; at `0.2` they keep glowing dimly in their flash colour, so a palette by position strobe leaves a faint rainbow in the room between flashes.

## Settings

| Setting          | What it does                                                                                     |
|------------------|--------------------------------------------------------------------------------------------------|
| Rate             | Flashes per second, 1 to 12. Smart bulbs top out around 12 and look best at 8 to 10.             |
| On Time          | Seconds a flash stays lit, 0.03 to 0.3, clamped to half the time between flashes.               |
| Spread           | Which lamps take part in a flash, see [Spreads](#spreads).                                       |
| Color Mode       | Where the flash colours come from, see [Color Modes](#color-modes).                              |
| Strobe Color     | The colour of the flashes in `strobe color` mode.                                                |
| Gate             | When the strobe runs, see [Gates](#gates).                                                       |
| Trigger, Steps Per Beat, Timer BPM | The steps for `beat bursts`, as in [Rave](rave.md#trigger).                    |
| Lead (advanced)                    | Seconds the steps fire ahead of the predicted beat, so slow lamps burst on the beat; about 0.05 to 0.1 for a Hue zone. |
| Burst Flashes    | Flashes per step for `beat bursts`, 1 to 16.                                                     |
| Threshold        | The band level the `level` gate needs, 0 to 1.                                                   |
| Band             | The frequency band the level gate listens to: `Full`, `Bass`, `Mids` or `High`.                  |
| Density          | The fraction of the lamps in every `scatter` flash.                                              |
| Sectors          | Groups for `corners`, `sweep` and `ripple`, 2 to 8.                                              |
| Tail             | Fade out over the gap to the next flash, 0 hard off to 1.                                        |
| Background       | Brightness of the lamp colours between flashes.                                                  |
| Layout           | Where the lamps stand: `Auto` uses the device positions when known, else `Ring`, `Line` or `Grid`. |
| Color Step (advanced) | How far along the palette `palette cycle` moves per flash.                                  |
| Reactive Depth, Sensitivity (advanced) | Scale the flash brightness with the band level, and the gain on that level. |
| Zones (advanced) | Number of lamps to split a strip into. 0 is one per pixel for bulbs, 8 for strips.              |

## Presets

| Preset             | Look                                                                      |
|--------------------|---------------------------------------------------------------------------|
| Tyc Sync Strobe    | Four white flashes at 8 Hz on every beat, every lamp in sync              |
| Club Strobe        | Continuous 10 Hz white strobe                                             |
| Tyc Rainbow Strobe | 8 Hz strobe with the palette laid round the room by position              |
| Confetti Strobe    | Half the lamps per flash in random palette colours                        |
| Lighthouse Strobe  | One sector per flash sweeping clockwise round the room                    |
| Triple Flash       | Three flashes every two beats, the last fading out                        |
| Ping Pong          | Front and back, then right and left halves taking turns at 6 Hz           |
| Corner Chase       | The four corners in turn, a new palette colour on every corner            |
| Bass Gate          | 10 Hz white strobe that only runs while the bass is loud                  |
| Slow Pulse         | Two soft 100 ms flashes a second, the palette colour changing every flash |

## Tips For Smart Bulbs

- A Hue entertainment zone streams at 30 frames per second and the bulbs themselves need a few tens of milliseconds to switch, so 8 to 10 flashes per second is the sweet spot: every flash is a clear pop. At 12 the flashes start to smear into a flicker on some bulbs; gradient strips keep up better than bulbs.
- All lamps of a flash are sent in the same frame, so bulbs and strip segments stay in sync. If one bulb lags behind the others it is a Zigbee problem (distance, interference), not a timing one.
- With `beat bursts` the strobe becomes a musical accent rather than a constant wall of light, and it is far easier on the eyes. `level` on the `Bass` band with a threshold around 0.5 gives a strobe that only opens on the drops.
- Keep **On Time** short (50 ms) for a hard pop. Longer on times at low rates (100 ms at 2 Hz) give the softer pulsing feel of a manual strobe button.
- On WLED strips the output is split into zones (8 by default), so `sweep` and `ripple` run along the strip in blocks and `scatter` flashes random blocks.
