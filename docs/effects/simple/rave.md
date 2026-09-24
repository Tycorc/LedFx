# Rave

## Overview

Rave is a party mode in the style of the "disco" and "party" modes found in smart bulb apps such as Hue Essentials and Hue Dynamic.

Where most LedFx effects paint a picture along a strip, Rave treats the output as a handful of independent lamps, called zones, and snaps them to new colours in hard steps on the beat. It was built for smart bulb setups such as a [Philips Hue entertainment zone](../../devices/hue.md), a room full of LIFX bulbs or a few Nanoleaf panels, where every pixel is a whole lamp and there is no "along the strip" to speak of. It also works on strips and matrices by splitting them into zones.

The steps that drive the pattern come from the beat tracker, from bass hits, from onsets, or from a plain timer. When no beat has been heard for a few seconds the timer takes over automatically, so the lights keep moving between tracks and the effect still works without any audio at all.

## Modes

| Mode        | What happens on every step                                                |
|-------------|---------------------------------------------------------------------------|
| `random`    | Every lamp picks a new colour from the palette, independently.            |
| `wash`      | All lamps snap to the same new colour.                                    |
| `chase`     | One lamp is lit at a time, and it moves to the next lamp.                 |
| `alternate` | Even and odd lamps show two colours from opposite ends of the palette and swap them. With a red / blue palette this is the classic police pattern. |
| `strobe`    | All lamps flash the strobe colour a few times per step.                   |

A lamp never gets the same colour twice in a row: the next colour is always at least 15% further along the palette, so every step is a visible change. The palette is the normal LedFx gradient picker.

## Settings

### Trigger

What advances the pattern.

- **Beat**: the BPM beat tracker. This is the tightest option for music with a steady beat, and it stays in time between detected beats because it follows the bar oscillator rather than single hits.
- **Bass hit**: a step on every bass hit, as used by the Strobe effect.
- **Onset**: a step on every onset, which fires on most percussive sounds.
- **Timer**: ignore the audio and step at a fixed tempo.

Beat, Bass hit and Onset all fall back to the timer after five seconds without a trigger.

### Steps Per Beat

How many colour changes happen per beat. `1/2` and `1/4` change every two or four beats, which suits slow washes. `2` and `4` change on the off beats and are what you want for a proper rave. With the Timer trigger this multiplies the timer tempo.

### Timer BPM

The tempo used by the Timer trigger, and by the fallback when no beat is heard.

### Fade

How much of each step the lamps spend fading to black. `0` holds the colour until the next step, which gives the hardest cuts. `1` fades all the way to black just as the next step lands, which turns every step into a pulse.

## Advanced Controls

### Zones

How many lamps the output is split into. `0` is automatic: every pixel is its own zone for outputs of up to 32 pixels, which covers every smart bulb setup, and larger outputs are split into 8 equal zones. Set it explicitly to group several bulbs together or to cut a strip into more or fewer blocks. It is capped at the pixel count.

### Flash Chance

The chance, per step, that all lamps flash the strobe colour instead of taking palette colours. A little of this, around 0.1, gives the occasional white hit that makes a random pattern feel like a light show.

### Strobe Color

The colour used by strobe mode and by accent flashes.

### Strobe Flashes

How many flashes fit into one step in strobe mode. Each flash stays on for at most 50 ms. Philips recommends that entertainment effects change no faster than about 12 times per second, and bulbs visibly lag behind anything quicker, so keep this low for Hue and use `1` with a slow Steps Per Beat for a bulb friendly strobe.

```{warning}
Flashing lights, and in particular whole room flashes faster than about three per second, can trigger seizures in people with photosensitive epilepsy. Check who is in the room before using strobe mode or a high Flash Chance.
```

## Presets

| Preset         | Mode      | Trigger | Steps / Beat | Fade | Notes                                    |
|----------------|-----------|---------|--------------|------|------------------------------------------|
| Club           | random    | Beat    | 1            | 0.35 | Dancefloor palette, 10% white flashes    |
| Rainbow Party  | random    | Beat    | 2            | 0    | Full rainbow, hard cuts on the off beat  |
| Strobe Drop    | strobe    | Beat    | 1            |      | Four white flashes per beat              |
| Police         | alternate | Timer   | 2            | 0    | Red and blue swapping at 300 changes/min |
| Round The Room | chase     | Beat    | 2            | 0.6  | One lamp at a time, cyan to pink         |
| Slow Wash      | wash      | Timer   | 1/2          | 0    | Everything changes colour every 2 s      |

## Tips For Smart Bulbs

Smart bulbs are slow compared to addressable LEDs. A Hue entertainment zone is streamed at 30 frames per second, the bridge passes on at most 25 updates per second, and Philips recommends effects change no faster than about 12 times per second, so fast steps smear into a blur. Steps Per Beat of `1` or `2` at typical dance tempos is the sweet spot.

Bulbs also run at full brightness by default. If a rave in the living room is too much, turn down the effect **Brightness** rather than the bulbs, so the contrast between steps is kept.
