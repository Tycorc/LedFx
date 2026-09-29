# Party

## Overview

Party is a show engine for a handful of lamps: ten effect families that play events on the beat, each with an envelope, a movement and a palette, and each able to follow the music level on top. It is built for a [Philips Hue entertainment zone](../../devices/hue.md) or any other lamp based device, and runs on strips and matrices by splitting them into zones.

Where [Light Show](light_show.md) snaps lamps to colours in hard steps, Party is smooth: every event rises, holds and falls with a chosen curve, movements glide from lamp to lamp, and colours come from a rolling palette. Where [Disco](disco.md) listens for hits, Party keeps time with the beat tracker and uses the music level to scale the show.

## How An Event Plays

Every step (a beat, or a fraction or multiple of one, see [Trigger](#trigger)) starts an **event**. An event has an envelope: **Attack** beats rising, **Hold** beats at full, **Release** beats falling, shaped by the **Curve**. The **family** decides how strongly each lamp takes part in the event and which palette colour it shows. Several events can overlap; each lamp shows the strongest one.

## Families

| Family    | What happens                                                                                     |
|-----------|--------------------------------------------------------------------------------------------------|
| `adsr`    | Every lamp plays a colour envelope over one step: a [shape](#shapes) such as a frosty white flash that cools to blue. |
| `chase`   | The envelope runs from lamp to lamp along the light order, each lamp **Stagger** beats after the previous one. Turns the room. |
| `radial`  | A ring that spreads from the **Origin** lamp outwards, as far as the **Radius**.                  |
| `wash`    | Three soft colour waves rolling along the lamps. **Radius** sets how wide they are.               |
| `scan`    | A bright line bouncing from one end of the lamps to the other and back, with a **Trail** behind it. |
| `streak`  | A comet crossing the lamps with a fading **Trail**, fired only with the given **Probability**.    |
| `twinkle` | On every step each lamp lights with the given **Probability**, so the room scatters.              |
| `breathe` | The whole room breathes as one, colours drifting along the palette from event to event.           |
| `gate`    | A wash that opens with the music level: brightness follows the band above the **Threshold**.      |
| `burst`   | Random lamps flash when the band accents above the **Threshold**, at most every 0.4 s.            |

### Direction

`forward`, `reverse`, `alternate` (every other event runs backwards) or `random`. Applies to chase, radial, wash, scan and streak.

### Light Order

`Position` runs chase, scan and streak along the pixel order, which on a Hue device is the light order you chose (set it to `Around the room` to turn the room, `Left to right` to sweep it). `Random` shuffles the lamps once per activation.

## Shapes

The `adsr` family plays one of these colour envelopes on every step:

| Shape           | Look                                                              |
|-----------------|-------------------------------------------------------------------|
| `Single colour` | The **Color** with a crisp attack, a short hold and a long tail.  |
| `Frost`         | A white flash that cools through cyan to blue and out.            |
| `Magenta`       | One rounded magenta pulse fading through violet to black.         |
| `Coral`         | A solid block of the **Color** with a hard edge in and out.       |
| `Rose`          | Dim violet unfolding into rose pink, then a long fade.            |
| `Ember`         | Warm white through gold and orange into a lingering red ember.    |
| `Spectrum`      | Red through gold, green, cyan and blue to a faint magenta.        |
| `Prism`         | Red first, then green, then a blue sustain.                       |

## Trigger

**Trigger**, **Steps Per Beat** and **Timer BPM** work as in [Rave](rave.md#trigger). Steps Per Beat is how many events start per beat: `1/4` starts one per bar, which suits the slow families (radial, wash, breathe), `1` one per beat, `2` or `4` for busy twinkles and bursts. When no beat is heard for five seconds the timer takes over.

## Reactive Settings

- **Band**: the frequency band the reactive level listens to: `Full`, `Bass` (20 to 250 Hz), `Mids` (250 Hz to 3 kHz) or `High` (3 to 9 kHz).
- **Reactive Depth**: how much the band level scales the brightness. `0` runs on the beat alone, `1` follows the level fully. At `0.6` a quiet passage dims the show to 40% and accents bring it back.
- **Threshold**: for `gate` and `burst`, the level the band must exceed before anything shows.
- **Sensitivity** and **Smoothing** (advanced): gain on the audio levels, and how much they are smoothed. Levels rise in about 30 ms and fall in about 220 ms, both scaled by smoothing.

## Flash Limit

With **Flash Limit** on (the default) no lamp can jump to bright more often than about three times a second, whatever the settings. Turn it off only if you know who is in the room.

```{warning}
Flashing lights, and in particular whole room flashes faster than about three per second, can trigger seizures in people with photosensitive epilepsy.
```

## Presets

| Preset             | Family  | Notes                                                    |
|--------------------|---------|----------------------------------------------------------|
| Frost Strike       | adsr    | Icy white to blue on every beat                          |
| Magenta Pulse      | adsr    | Hot magenta pulse                                        |
| Coral Pop          | adsr    | Solid coral block                                        |
| Rose Bloom         | adsr    | Violet to rose, slow                                     |
| Ember Flare        | adsr    | Warm white to red ember                                  |
| Spectrum Drop      | adsr    | Red sweeping to blue                                     |
| Prism Fall         | adsr    | Red, green, then blue                                    |
| Domino Run         | chase   | Neon chase tumbling round the room once per bar          |
| Bass Ring          | radial  | A ring from the centre on the bass, once per bar         |
| Aurora Roll        | wash    | Slow cool washes, alternating direction                  |
| Ricochet           | scan    | A vivid line bouncing end to end                         |
| Comet Trail        | streak  | Random comets with long trails                           |
| Star Scatter       | twinkle | Sparse pale twinkles every beat                          |
| Deep Breath        | breathe | The whole room breathing in velvet colours               |
| Volume Glow        | gate    | A warm wash that opens with the music level              |
| Confetti Burst     | burst   | Colour bursts on high band accents                       |
| Tyc Room Turn      | chase   | Full rainbow turning round the room twice a beat         |
| Tyc Scatter Strobe | twinkle | Half the lamps strobing white, cyan and pink twice a beat|

## Strips And Matrices

On a WLED strip or matrix the output is split into 8 zones (or the number set in **Zones**), so chase, scan and streak run along the strip in blocks and twinkle scatters over them.
