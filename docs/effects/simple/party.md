# Party

## Overview

Party is a show engine for a handful of lamps: thirteen effect families that play events on the beat, each with an envelope, a movement and a palette, and each able to follow the music level on top. It is built for a [Philips Hue entertainment zone](../../devices/hue.md) or any other lamp based device, and runs on strips and matrices by splitting them into zones.

Where [Light Show](light_show.md) snaps lamps to colours in hard steps, Party is smooth: every event rises, holds and falls with a chosen curve, movements glide from lamp to lamp, and colours come from a rolling palette. Where [Disco](disco.md) listens for hits, Party keeps time with the beat tracker and uses the music level to scale the show. When the lamps' positions are known, the movements run through the room itself: a chase around the room, a ring from its centre, a wash rolling from the back to the front.

## How An Event Plays

Every step (a beat, or a fraction or multiple of one, see [Trigger](#trigger)) starts an **event**. An event has an envelope: **Attack** beats rising, **Hold** beats at full, **Release** beats falling, shaped by the **Curve**. The **family** decides how strongly each lamp takes part in the event and which palette colour it shows. Several events can overlap; each lamp shows the strongest one.

## Families

| Family      | What happens                                                                                     |
|-------------|--------------------------------------------------------------------------------------------------|
| `adsr`      | Every lamp plays a colour envelope over one step: a [shape](#shapes) such as a frosty white flash that cools to blue. |
| `chase`     | The envelope runs from lamp to lamp along the [light order](#light-order), each lamp **Stagger** beats after the previous one. With the `Room` order it turns the room. |
| `radial`    | A ring that spreads from the **Origin** outwards, as far as the **Radius**. With positions the ring grows from the real centre of the room. |
| `wash`      | Three soft colour waves rolling across the room along the **Heading**. **Radius** sets how wide they are. |
| `scan`      | A bright line bouncing from one side of the room to the other and back along the **Heading**, with a **Trail** behind it. |
| `streak`    | A comet crossing the room along the **Heading** with a fading **Trail**, fired only with the given **Probability**. |
| `twinkle`   | On every step each lamp lights with the given **Probability**, so the room scatters. With positions the lit lamps are spread over the room. |
| `breathe`   | The whole room breathes as one, colours drifting along the palette from event to event.           |
| `gate`      | A wash that opens with the music level: brightness follows the band above the **Threshold**.      |
| `burst`     | Random lamps flash when the band accents above the **Threshold**, at most every 0.4 s.            |
| `lightning` | A strike: one to three white flashes with a flicker between them, then an after-glow in the palette colour that fades over the **Release**. Each lamp joins a strike with the given **Probability**; between strikes the room keeps a dim, slowly wobbling glow of the palette. |
| `fireworks` | A burst on one lamp (a different one every time) that spreads to its neighbours, the farthest **Stagger** beats later and dimmer, as far as the **Radius**, and fades with a sparkle in the tail. |
| `pulse`     | Every lamp is a level meter: its brightness follows its band above the **Threshold**, with a faint floor when the band is silent. With **Band** on `Full` the lamps are shared between bass, mids and high along the light order and coloured from thirds of the palette; any other band drives every lamp. |

### Direction

`forward`, `reverse`, `alternate` (every other event runs backwards) or `random`. Applies to chase, radial, wash, scan and streak.

### Light Order

- `Position` runs chase, scan, streak and pulse along the pixel order, which on a Hue device is the light order you chose.
- `Room` runs them around the room by angle, clockwise from the front, when the positions are known.
- `Heading` runs them along the **Heading** (see [Room Positions](#room-positions)), so a chase with heading 90 sweeps from left to right.
- `Random` shuffles the lamps once per activation.

Without positions `Room` and `Heading` fall back to `Position`.

## Room Positions

A Hue entertainment zone knows where every lamp (and every segment of a gradient strip) stands, so Party can move through the room instead of along the lamp numbers. **Layout** (advanced) chooses where the positions come from: `Auto` uses the device positions when every device of the virtual knows them and otherwise runs along the light order, which is what a strip wants; `Ring`, `Line` and `Grid` force a synthetic layout, for example to make a WLED strip behave like a ring of lamps around the room.

With positions:

- **Heading** (0 to 359 degrees) is the direction the wash, scan and streak travel: 0 towards the front of the room (the TV side), 90 towards the right (the default, so waves roll from left to right), 180 towards the back, 270 towards the left. A wash with heading 0 rolls from the back of the room to the front.
- **Origin** places the start of the radial ring on the heading axis through the room: `0.5` is the centre of the room, `0` and `1` the two ends of the room along the heading. The ring measures its distance to every lamp for real: the lamp nearest the origin lights first and the farthest last, and lamps at the same distance (four bulbs in the corners, say) light together.
- Twinkle, burst and lightning pick lamps that are spread over the room rather than rolling the dice per lamp, so half the lamps means every other lamp around the room.
- Fireworks spread by real distance from the lamp that bursts.

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

**Trigger**, **Steps Per Beat** and **Timer BPM** work as in [Rave](rave.md#trigger). Steps Per Beat is how many events start per beat: `1/4` starts one per bar, which suits the slow families (radial, wash, breathe), `1` one per beat, `2` or `4` for busy twinkles and bursts. When no beat is heard for five seconds the timer takes over. Lightning and fireworks usually want `1/2` or `1/4` with a **Probability** below one, so strikes and bursts come when they come.

## Reactive Settings

- **Band**: the frequency band the reactive level listens to: `Full`, `Bass` (20 to 250 Hz), `Mids` (250 Hz to 3 kHz) or `High` (3 to 9 kHz). For `pulse` it also decides which lamps follow which band.
- **Reactive Depth**: how much the band level scales the brightness. `0` runs on the beat alone, `1` follows the level fully. At `0.6` a quiet passage dims the show to 40% and accents bring it back. `gate` and `burst` need the level to work, so while the setting is left at `0` they use 0.8 and 0.6.
- **Threshold**: for `gate`, `burst` and `pulse`, the level the band must exceed before anything shows.
- **Sensitivity** and **Smoothing** (advanced): gain on the audio levels, and how much they are smoothed. Levels rise in about 30 ms and fall in about 220 ms, both scaled by smoothing.

## Flash Limit

With **Flash Limit** on (the default) no lamp can jump to bright more often than about three times a second, whatever the settings. A lightning strike counts as one flash: its flicker only dips to 60%, so the limiter lets the whole strike through. Turn it off only if you know who is in the room.

```{warning}
Flashing lights, and in particular whole room flashes faster than about three per second, can trigger seizures in people with photosensitive epilepsy. Lightning with a probability of 1 flashes the whole room; keep the flash limit on and the steps per beat low.
```

## Presets

| Preset             | Family    | Notes                                                    |
|--------------------|-----------|----------------------------------------------------------|
| Frost Strike       | adsr      | Icy white to blue on every beat                          |
| Magenta Pulse      | adsr      | Hot magenta pulse                                        |
| Coral Pop          | adsr      | Solid coral block                                        |
| Rose Bloom         | adsr      | Violet to rose, slow                                     |
| Ember Flare        | adsr      | Warm white to red ember                                  |
| Spectrum Drop      | adsr      | Red sweeping to blue                                     |
| Prism Fall         | adsr      | Red, green, then blue                                    |
| Domino Run         | chase     | Neon chase tumbling along the lamps once per bar         |
| Bass Ring          | radial    | A ring from the centre on the bass, once per bar         |
| Aurora Roll        | wash      | Slow cool washes rolling across the room, alternating    |
| Ricochet           | scan      | A vivid line bouncing from left to right and back        |
| Comet Trail        | streak    | Random comets with long trails                           |
| Star Scatter       | twinkle   | Sparse pale twinkles every beat                          |
| Deep Breath        | breathe   | The whole room breathing in velvet colours               |
| Volume Glow        | gate      | A warm wash that opens with the music level              |
| Confetti Burst     | burst     | Colour bursts on high band accents                       |
| Tyc Room Turn      | chase     | Full rainbow turning round the room twice a beat         |
| Tyc Scatter Strobe | twinkle   | Half the lamps strobing white, cyan and pink twice a beat|
| Tyc Thunder        | lightning | White strikes on half the lamps every other beat, violet after-glow over a storm blue glow |
| Storm Front        | lightning | Whole room strikes once a bar with a long cold after-glow |
| Sky Burst          | fireworks | A gold, pink or cyan burst from one lamp spreading over the room every beat |
| Ember Shower       | fireworks | Slow warm bursts, sparkling embers, once per bar         |
| Band Meter         | pulse     | Bass red, mids green, high blue, every lamp a meter      |
| Bass Meter         | pulse     | The whole room follows the bass in deep colours          |
| Room Chase         | chase     | A chase running clockwise around the room twice a beat   |
| Centre Ring        | radial    | A ring growing from the real centre of the room on every beat, bass reactive |
| Front Wash         | wash      | Warm to cool waves rolling from the back of the room to the front |
| Side Scan          | scan      | A warm line bouncing left to right, alternating           |
| Corner Comet       | streak    | Comets crossing the room diagonally                      |

## Strips And Matrices

On a WLED strip or matrix the output is split into 8 zones (or the number set in **Zones**), so chase, scan and streak run along the strip in blocks and twinkle scatters over them. Set **Layout** to `Ring` to treat the zones as lamps around the room, or `Grid` on a matrix so the wash and the ring move over its surface.

## Tips For Smart Bulbs

- Hue bulbs ramp rather than snap: give every family at least a little **Attack** and **Release** (0.05 beats and up) and let the flash limit do the rest.
- Lightning reads best with the gradient in blues and violets: the flash itself is white, the palette only colours the after-glow and the storm glow.
- For fireworks on a zone of a few bulbs, keep **Radius** at 1 so the burst reaches the whole room, and raise **Stagger** to 0.5 beats to see it spread.
- Pulse on `Full` needs at least three lamps to show all three bands; with a gradient strip in the zone the strip's segments count as lamps.
