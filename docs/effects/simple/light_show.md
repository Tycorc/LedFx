# Light Show

## Overview

Light Show is the pattern library for a room of lamps: strobe cycles, scatter glows, stage strobes, fills, palette loops, waves, and backlit variants of all of them. Dozens of named party effects boil down to a combination of four things, which is what Light Show exposes:

- **Pattern**: which lamps light up on each step.
- **Envelope**: what a lit lamp does during the step.
- **Colour mode**: where the lamp colours come from.
- **Backlight**: what the lamps that are not lit show.

Like [Rave](rave.md), the output is treated as a handful of independent lamps (one per pixel on a [Hue entertainment zone](../../devices/hue.md), 8 blocks on a long strip) and the steps come from the beat tracker, bass hits, onsets or a timer. When no beat has been heard for five seconds the timer takes over so the show keeps going between tracks and without any audio at all.

## Auto Mode

Set **Pattern**, **Envelope** or **Colour mode** (or all three) to `auto` and Light Show runs its own show, like the autopilot of a DJ app. Every **Auto Steps** steps (16 by default, four bars at one step per beat) the settings on auto change to something else. The choice follows the music: while the bass is loud the picks come from the harder set (`all`, `stage`, `double`, `split`, `scatter` patterns with `strobe`, `flare`, `fade` or `hold` envelopes), in quieter passages from the softer set (`cycle`, `fill`, `wave`, `loop` patterns with `fade`, `glow`, `grow` or `hold`). Settings that are not on auto are left alone, so `cycle` pattern with `auto` envelope walks round the room forever while the envelope changes.

The *Tyc Autopilot* preset is the no hands option for a party. To switch between whole effects automatically, for example between Tyc Autopilot, Disco, Party and Rave, put them in scenes and use a LedFx playlist in shuffle mode.

## Patterns

| Pattern          | Lamps lit on each step                                                     |
|------------------|----------------------------------------------------------------------------|
| `auto`           | Picked automatically, see [Auto Mode](#auto-mode).                         |
| `all`            | Every lamp.                                                                |
| `cycle`          | One lamp, the next one in light order every step.                          |
| `scatter`        | One lamp at random, never the same one twice in a row.                     |
| `double`         | Two lamps opposite each other, moving round every step.                    |
| `double scatter` | Two random lamps.                                                          |
| `stage`          | The lamps are split into **Stages** groups (lamp 1, 4, 7... is stage 1 and so on) and the stages take turns. |
| `fill`           | One more lamp every step, in order, until the room is full, then it clears and starts again. |
| `scatter fill`   | The same, in a random order that changes every round.                      |
| `split`          | The first half of the lamps, then the second half. With the Hue light order set to `Left to right` this is a left / right split, `Front to back` gives front / back. |
| `wave`           | Every lamp, with a brightness wave travelling along the lamps one full cycle per step. **Stages** is the number of peaks across the room. |
| `loop`           | Every lamp, with the palette spread along the lamps and walking one lamp per step. **Stages** is how many times the palette repeats across the room. |

## Envelopes

| Envelope | During the step                                                             |
|----------|-----------------------------------------------------------------------------|
| `auto`   | Picked automatically, see [Auto Mode](#auto-mode).                           |
| `strobe` | A short flash of at most 50 ms, **Strobe Flashes** times per step, then off. |
| `hold`   | On for the whole step, hard cut at the next.                                 |
| `fade`   | Full at the start of the step, fading to the backlight by the next step.     |
| `grow`   | The reverse: rising from the backlight to full just as the next step lands.  |
| `glow`   | A soft rise and fall.                                                        |
| `flare`  | Starts on the **Flare Color** (white by default), settles onto the lamp colour and dims a little towards the next step. |

## Colour Modes

| Colour mode | Where colours come from                                                    |
|-------------|----------------------------------------------------------------------------|
| `auto`      | Picked automatically, see [Auto Mode](#auto-mode).                         |
| `cycle`     | The lit lamps take the same colour, and it moves **Color Step** along the palette every step. A hard edged three colour palette with a step of 0.34 gives the classic red, white, blue palette strobe. A step of 0 keeps one colour. |
| `random`    | Every lit lamp picks its own random palette colour, always at least 15% along from its last one. |
| `per lamp`  | Each lamp has a fixed position on the palette: the first lamp the start, the last lamp the end. With a two colour palette and the `split` pattern this gives the two colour left / right shows. |

## Backlight

The **Backlight** colour and **Backlight Brightness** are what the unlit lamps show. `0` brightness turns them off, which is the normal look. A dim backlight turns any pattern into its "backlit" variant, for example a white strobe cycling over a dim red room.

## Trigger Settings

**Trigger**, **Steps Per Beat** and **Timer BPM** work exactly as in [Rave](rave.md#trigger): Beat follows the BPM tracker and stays in time between detected beats, Bass hit and Onset fire on percussive sounds, and Timer ignores the audio.

## Advanced Controls

**Auto Steps** is the number of steps between automatic changes. **Zones** splits the output into a number of lamps (`0` is automatic), **Color Step** is described under colour modes, **Strobe Flashes** is the number of flashes per step for the strobe envelope, and **Flare Color** is the colour a flare starts from.

```{warning}
Flashing lights, and in particular whole room flashes faster than about three per second, can trigger seizures in people with photosensitive epilepsy. Check who is in the room before using the strobe envelope at high step rates.
```

## Presets

| Preset                 | Pattern | Envelope | Colours  | Notes                                             |
|------------------------|---------|----------|----------|---------------------------------------------------|
| Tyc Autopilot          | auto    | auto     | auto     | Changes every four bars, harder when loud         |
| Tyc Autopilot Backlit  | auto    | auto     | auto     | Two steps a beat over a dim blue room, 8 bars     |
| Orbit Strobe           | cycle   | strobe   | cycle    | One blue flash walking round the room             |
| Tyc Party Strobe       | all     | strobe   | random   | Every lamp a random rainbow colour, twice a beat  |
| Scatter Glow           | scatter | fade     | cycle    | Pink fades on random lamps                        |
| Tricolour Strobe       | all     | strobe   | cycle    | Red, white, blue on successive beats              |
| Ember Orbit            | cycle   | strobe   | cycle    | White flash cycling over a dim red room           |
| Room Fill              | fill    | hold     | cycle    | Orange and blue lamps filling up the room         |
| Triad Strobe           | stage   | strobe   | cycle    | Three groups of lamps taking turns                |
| Skyburst               | scatter | flare    | random   | White bursts settling into rainbow colours        |
| Half And Half          | split   | fade     | per lamp | Blue half, red half                               |
| Tide                   | wave    | hold     | per lamp | Orange to blue wave, one cycle every two beats    |
| Carousel               | loop    | hold     | per lamp | The rainbow walking round the room                |
| Tyc Vortex             | loop    | glow     | per lamp | Pink and green chasing, two repeats               |
| Blue Light             | split   | strobe   | per lamp | Red and blue halves flashing at 300 changes/min   |

## Strips And Matrices

Light Show is not limited to bulbs. On a WLED strip or matrix the output is split into 8 zones (or the number set in **Zones**), so a strip becomes a row of eight virtual lamps and the same patterns run along it. **Zones** set to the number of segments in the room, for instance one per wall, is a good starting point.

## Building Your Own

Most named party effects are one setting away from a preset:

- A fade or grow cycle: Orbit Strobe with the `fade` or `grow` envelope.
- A scatter strobe or scatter grow: Scatter Glow with the `strobe` or `grow` envelope.
- Two lamps at a time: the `double` and `double scatter` patterns with `strobe`.
- Five stages: the `stage` pattern with Stages 5 and any envelope.
- A four beat fill: the `fill` pattern with Zones 4.
- Backlit anything: the same show with a backlight colour and some backlight brightness.
- A double wave or a thin loop: `wave` with Stages 2, `loop` with Stages 3.
- Fixed colours per lamp: `all` with `hold` and `per lamp` colours on any palette.
- Front and back, or two corners: the `split` pattern with the Hue device's light order set to `Front to back` or `Around the room`.
