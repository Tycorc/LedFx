# Light Show

## Overview

Light Show is the pattern library for a room of lamps: strobe cycles, scatter glows, stage strobes, fills, sweeps, paint overs, palette loops, waves, peak flashes, and backlit variants of all of them. Dozens of named party effects boil down to a combination of a few things, which is what Light Show exposes:

- **Pattern**: which lamps light up on each step.
- **Envelope**: what a lit lamp does during the step.
- **Colour mode**: where the lamp colours come from.
- **Grouping**: whether "next", "half" and "opposite" follow the light order or the real positions of the lamps in the room.
- **Backlight**: what the lamps that are not lit show.
- **Trail** and **Rhythm**: how long a lamp keeps going after its step, and which steps of a bar fire.

Like [Rave](rave.md), the output is treated as a handful of independent lamps (one per pixel on a [Hue entertainment zone](../../devices/hue.md), 8 blocks on a long strip) and the steps come from the beat tracker, bass hits, onsets or a timer. When no beat has been heard for five seconds the timer takes over so the show keeps going between tracks and without any audio at all. Every lamp runs its own envelope clock, so lamps lit on different steps fade independently.

## Auto Mode

Set **Pattern**, **Envelope** or **Colour mode** (or all three) to `auto` and Light Show runs its own show, like the autopilot of a DJ app. Every **Auto Steps** steps (16 by default, four bars at one step per beat) the settings on auto change to something else. The choice follows the music: while the bass is loud the picks come from the harder set (`all`, `stage`, `double`, `split`, `flip`, `scatter`, `double scatter`, `sprinkle`, `scatter fill` and `sweep` patterns with `strobe`, `flare`, `fade`, `hold`, `pulse` or `peak` envelopes), in quieter passages from the softer set (`cycle`, `fill`, `stage fill`, `paint`, `chase`, `ramp`, `wave`, `loop`, `scatter` and `double` patterns with `fade`, `glow`, `grow`, `hold`, `cross fade`, `swell` or `dip`). Settings that are not on auto are left alone, so `cycle` pattern with `auto` envelope walks round the room forever while the envelope changes.

The *Tyc Autopilot* preset is the no hands option for a party. To switch between whole effects automatically, for example between Tyc Autopilot, Disco, Party and Rave, put them in scenes and use a LedFx playlist in shuffle mode.

## Patterns

Several patterns work on **groups** of lamps: the lamps are split into **Stages** groups (with the `order` grouping lamp 1, 4, 7... is group 1 and so on, with the `room` grouping the groups are areas of the room, see [Room Grouping](#room-grouping)).

| Pattern          | Lamps lit on each step                                                     |
|------------------|----------------------------------------------------------------------------|
| `auto`           | Picked automatically, see [Auto Mode](#auto-mode).                         |
| `all`            | Every lamp.                                                                |
| `cycle`          | One lamp, the next one in light order (or around the room) every step.     |
| `scatter`        | One lamp at random, never the same one twice in a row.                     |
| `double`         | Two lamps opposite each other, moving round every step.                    |
| `double scatter` | Two random lamps.                                                          |
| `sprinkle`       | **Stages** random lamps, a different set every step.                       |
| `stage`          | The groups take turns, one group per step.                                 |
| `stage fill`     | One more group every step until the room is full, then it clears and starts again. |
| `fill`           | One more lamp every step, in order, until the room is full, then it clears and starts again. |
| `scatter fill`   | The same, in a random order that changes every round.                      |
| `paint`          | One more group every step, but a full room does not clear: the next round paints a new colour over the old one, group by group. |
| `scatter paint`  | The same, with the groups in a random order every round.                   |
| `sweep`          | The groups fill up one per step, then empty out one per step in the same order, so a block of light travels through the room. |
| `split`          | The first half of the lamps, then the second half. With the `room` grouping this is the left and the right half of the room. |
| `flip`           | Every other lamp, then the ones in between.                                |
| `chase`          | A block of **Stages** consecutive lamps moving one lamp per step.          |
| `ramp`           | One group at a time, brightening in four steps: dark, a quarter, half, three quarters. |
| `wave`           | Every lamp, with a brightness wave travelling along the lamps one full cycle per step. **Stages** is the number of peaks across the room. |
| `loop`           | Every lamp, with the palette spread along the lamps and walking one lamp per step. **Stages** is how many times the palette repeats across the room. |

`stage fill`, `paint`, `scatter paint` and `sweep` change colour once per round rather than once per step in `cycle` colour mode, and **Rest Steps** dark steps can follow every round of the fill, paint and sweep patterns.

## Envelopes

| Envelope     | During the step                                                         |
|--------------|-------------------------------------------------------------------------|
| `auto`       | Picked automatically, see [Auto Mode](#auto-mode).                       |
| `strobe`     | A short flash of at most **Flash Length** (50 ms by default), **Strobe Flashes** times per step, then off. |
| `hold`       | On for the whole step, hard cut at the next.                             |
| `fade`       | Full at the start of the step, fading to the backlight by the next step. |
| `grow`       | The reverse: rising from the backlight to full just as the next step lands. |
| `glow`       | A soft rise and fall.                                                    |
| `flare`      | Starts on the **Flare Color** (white by default), settles onto the lamp colour and dims a little towards the next step. |
| `dip`        | The reverse of a fade: the whole room stays on in the lamp colours and the lit lamps dip out to black over the step. |
| `peak`       | Swells up over the first half of the step, flashes the **Flare Color** at the top, and swells back down. |
| `pulse`      | **Strobe Flashes** pulses, each on for an eighth of the step and off for the next eighth, then dark for the rest of the step. Three pulses over a four beat step is the classic triple. |
| `cross fade` | On for the whole step, blending from the colour the lamp had before the step to its new colour. |
| `swell`      | On for the whole step at a brightness that follows a slow sine over the steps: a full swell and dip every 32 steps. |

## Colour Modes

| Colour mode | Where colours come from                                                    |
|-------------|----------------------------------------------------------------------------|
| `auto`      | Picked automatically, see [Auto Mode](#auto-mode).                         |
| `cycle`     | The lit lamps take the same colour, and it moves **Color Step** along the palette every step. A hard edged three colour palette with a step of 0.34 gives the classic red, white, blue palette strobe. A step of 0 keeps one colour. |
| `random`    | Every lit lamp picks its own random palette colour, always at least 15% along from its last one. |
| `per lamp`  | Each lamp has a fixed position on the palette: the first lamp the start, the last lamp the end (around the room with the `room` grouping). With a two colour palette and the `split` pattern this gives the two colour left / right shows. |
| `per group` | Each group has its own palette colour, and the colours move on by one group every step. With four corner groups and a two colour palette the room is split in two halves whose divide turns a quarter every step. |

## Room Grouping

**Grouping** decides what "next", "half", "opposite" and "group" mean:

- `order` follows the light order of the device: the Hue device's light order setting or the pixel order of a strip. This is the classic behaviour.
- `room` follows the positions of the lamps. A Hue entertainment zone knows where every lamp is from the Hue app, so a gradient strip flows along its length and the two ends of the room can be told apart. With `room`:
  - `cycle`, `fill`, `chase`, `wave`, `loop`, `flip` and `per lamp` colours run around the room clockwise from the front.
  - `stage`, `stage fill`, `paint`, `sweep`, `ramp` and `per group` colours use balanced areas of the room: 1 group is the whole room, 2 groups are front and back, 4 groups are the four corners, other counts are spread evenly around the room.
  - `split` is the left and the right half.
  - `double` lights a lamp and the one across the room from it.
  - `scatter`, `double scatter` and `sprinkle` spread their lamps: a new lamp is never next to the previous one, and two lamps lit together are never neighbours, as long as the room allows it.

**Layout** (advanced) is where the lamps are for the `room` grouping. `Auto` uses the device positions whenever every device in the virtual knows them, a grid for a matrix virtual and a ring otherwise. `Ring`, `Line` and `Grid` force a synthetic layout, which is how a WLED strip becomes a ring around the room or a line along a wall. On a strip split into **Zones**, every zone sits at the middle of its pixels.

## Backlight

The **Backlight** colour and **Backlight Brightness** are what the unlit lamps show. `0` brightness turns them off, which is the normal look. A dim backlight turns any pattern into its "backlit" variant, for example a white strobe cycling over a dim red room. A backlight at full brightness in the second colour of a two colour show gives the "one lamp in colour B, the rest in colour A" strobe cycles. The `dip` envelope ignores the backlight, because the room is lit in the lamp colours.

## Trail And Rhythm

**Trail** (advanced) is how many steps a lamp's envelope keeps running after the step that lit it. At 1 every lamp stops when the next step lands. At 2 a `cycle` with `fade` has two lamps fading at once, the newer one brighter, and a `hold` keeps the last two lamps on. At 8 with `scatter` and `fade` at two steps a beat, random lamps light up and take four beats to die down while new ones keep coming, the smouldering look. Fill, paint and sweep lamps stay on regardless.

**Rest Steps** (advanced) are dark steps after every round of the `fill`, `scatter fill`, `stage fill`, `paint`, `scatter paint` and `sweep` patterns. A two group `sweep` at two steps a beat with four rest steps gives the classic front to back sweep with a two beat pause.

**Rhythm** (advanced) picks which steps of a bar fire. The rhythms are written for four steps per beat, so 16 steps make a bar. On a firing step the pattern moves on, on a holding step the lamps keep what they have (a `hold` stays on, a `fade` keeps fading, stretched until the next firing step), and on an off step the room goes dark.

| Rhythm      | Bar (x fires, . holds, o all off)      | Feel                                        |
|-------------|----------------------------------------|---------------------------------------------|
| `steady`    | every step                             | The normal show                             |
| `downbeat`  | `x...x...x...x.x.`                     | Four to the floor with a push before the bar |
| `offbeat`   | `x..x..x...x.x...`                     | A syncopated three step figure              |
| `chop`      | `x.o.x.o.x.o.x.o.`                     | Every beat with a hard cut to black in between |
| `half time` | `x.x.x...x.x.x...`                     | Doubled hits on the first two beats         |
| `breaks`    | `x.o...x.....x...`                     | A sparse break beat                         |
| `pairs`     | `xxoo`                                 | Two steps on, two off, at any step rate     |
| `sparse`    | two bars of scattered hits             | Random looking accents over a lit room      |

## Trigger Settings

**Trigger**, **Steps Per Beat** and **Timer BPM** work exactly as in [Rave](rave.md#trigger): Beat follows the BPM tracker and stays in time between detected beats, Bass hit and Onset fire on percussive sounds, and Timer ignores the audio. The classic effects run at very different rates: strobe cycles and fades at one step per beat, fills, sweeps and dips at two steps per beat or one step every two beats, scatter strobes and ramps at four steps per beat, peak flashes, cross fades and triple pulses at one step every four beats.

## Flash Limit

**Flash Limit** is on by default: no lamp is allowed to jump to bright more than about three times a second, whatever the other settings say. A flash that comes too soon after the previous one on the same lamp is held dark. Scatter and cycle strobes are not affected because every flash lands on another lamp; whole room strobes faster than three per second are. Turn it off for a hard strobe, after checking who is in the room.

## Advanced Controls

**Auto Steps** is the number of steps between automatic changes. **Zones** splits the output into a number of lamps (`0` is automatic), **Layout** is described under [Room Grouping](#room-grouping), **Color Step** under colour modes, **Strobe Flashes** is the number of flashes per step for the strobe envelope and of pulses for the pulse envelope, **Flash Length** is the longest a strobe flash stays on, **Flare Color** is the colour a flare starts from and the peak colour of the peak envelope, and **Trail**, **Rest Steps** and **Rhythm** are described under [Trail And Rhythm](#trail-and-rhythm).

```{warning}
Flashing lights, and in particular whole room flashes faster than about three per second, can trigger seizures in people with photosensitive epilepsy. Check who is in the room before turning Flash Limit off or using the strobe envelope at high step rates.
```

## Presets

| Preset                 | Pattern       | Envelope   | Colours   | Notes                                                        |
|------------------------|---------------|------------|-----------|--------------------------------------------------------------|
| Tyc Autopilot          | auto          | auto       | auto      | Changes every four bars, harder when loud                    |
| Tyc Autopilot Backlit  | auto          | auto       | auto      | Two steps a beat over a dim blue room, 8 bars                |
| Orbit Strobe           | cycle         | strobe     | cycle     | One blue flash walking round the room                        |
| Tyc Party Strobe       | all           | strobe     | random    | Every lamp a random rainbow colour, twice a beat             |
| Scatter Glow           | scatter       | fade       | cycle     | Pink fades on random lamps                                   |
| Tricolour Strobe       | all           | strobe     | cycle     | Red, white, blue on successive beats                         |
| Ember Orbit            | cycle         | strobe     | cycle     | White flash cycling over a dim red room                      |
| Room Fill              | fill          | hold       | cycle     | Orange and blue lamps filling up the room                    |
| Triad Strobe           | stage         | strobe     | cycle     | Three groups of lamps taking turns                           |
| Skyburst               | scatter       | flare      | random    | White bursts settling into rainbow colours                   |
| Half And Half          | split         | fade       | per lamp  | Blue half, red half                                          |
| Tide                   | wave          | hold       | per lamp  | Orange to blue wave, one cycle every two beats               |
| Carousel               | loop          | hold       | per lamp  | The rainbow walking round the room                           |
| Tyc Vortex             | loop          | glow       | per lamp  | Pink and green chasing, two repeats                          |
| Blue Light             | split         | strobe     | per lamp  | Red and blue halves flashing at 300 changes/min              |
| Tyc Corner Stage       | stage         | strobe     | cycle     | The four corners of the room flashing in turn                |
| Tyc Turning Halves     | all           | hold       | per group | Red and blue halves whose divide turns a quarter every beat  |
| Corner Paint           | paint         | hold       | cycle     | Orange painted over blue corner by corner, then blue over orange |
| Bow To Stern           | sweep         | hold       | cycle     | A block of light sweeping front to back with a two beat pause |
| Ripple Fade            | split         | fade       | cycle     | Left and right fades overlapping, colours alternating        |
| Soft Dip               | stage         | dip        | cycle     | A warm lit room where one corner at a time dips out          |
| Peak Pop               | all           | peak       | cycle     | A magenta swell every two beats with a white peak            |
| Triple Beat            | all           | pulse      | cycle     | Three cyan pulses then a rest, every four beats              |
| Slow Blend             | all           | cross fade | cycle     | Blue to purple to blue, four beats each way                  |
| Pencil Ramp            | ramp          | hold       | random    | Each corner sketched in over a beat in a new colour          |
| Ember Pot              | scatter       | fade       | random    | Random embers smouldering for four beats                     |
| Rolling Block          | chase         | hold       | per lamp  | A three lamp rainbow block rolling round the room            |
| Palette Sprinkle       | sprinkle      | hold       | random    | Three random lamps in three random colours every beat        |
| Floor Hits             | scatter       | hold       | cycle     | A four to the floor scatter strobe on a downbeat rhythm      |
| Tyc Hard Strobe        | all           | strobe     | cycle     | A white 10 Hz strobe from a timer, flash limit off           |

## Strips And Matrices

Light Show is not limited to bulbs. On a WLED strip or matrix the output is split into 8 zones (or the number set in **Zones**), so a strip becomes a row of eight virtual lamps and the same patterns run along it. **Zones** set to the number of segments in the room, for instance one per wall, is a good starting point. With the `room` grouping and the `Ring` layout a strip around the room gets the corner stages and the left / right split, and a matrix virtual gets a grid.

## Building Your Own

Most named party effects are one setting away from a preset:

- A fade or grow cycle: Orbit Strobe with the `fade` or `grow` envelope.
- A scatter strobe or scatter grow: Scatter Glow with the `strobe` or `grow` envelope, at four steps a beat for the fast one.
- Two lamps at a time: the `double` and `double scatter` patterns with `strobe`.
- Five stages: the `stage` pattern with Stages 5 and any envelope; a three stage fill: `stage fill` with Stages 3.
- Two colour strobe cycles, one lamp in the second colour and the rest in the first: `cycle` with `hold`, a single colour palette and the backlight at full brightness in the other colour.
- A double strobe, every lamp flashing twice before the next one: `cycle` or `scatter` with `strobe`, Strobe Flashes 2 and Flash Length 0.12.
- A double fill, left then right then off again: `sweep` with Stages 2 and the `room` grouping (use `split` colours with `per group` for two colours).
- A blend between opposite corners: `all` with `cross fade`, `per group` colours and Stages 2, one step every two beats.
- The front to back sweep with a pause: Bow To Stern.
- A rhythmic strobe: `scatter` with `hold` at four steps a beat and a `downbeat`, `offbeat`, `chop`, `half time` or `breaks` rhythm; `sparse` with `flare`, a single colour palette and the backlight at full brightness in that colour for accents blending back into a lit room.
- Fixed colours per group: `all` with `hold` and `per group` colours on any palette.
- Backlit anything: the same show with a backlight colour and some backlight brightness.
- A double wave or a thin loop: `wave` with Stages 2, `loop` with Stages 3.
- Long fades on the whole room: `all` with `fade` at one step every two or four beats, or Trail 4 at one step a beat.
- Front and back, two corners, or left and right: the `room` grouping with `stage` (Stages 2 or 4) or `split`, on any device with positions and on a strip with the `Ring` layout.
