# Orbit

## Overview

Orbit is the spatial show engine: every lamp is coloured by **where it stands in the room** and a colour field moves over the room, so the whole room turns, flows, floods or scatters as one thing. It is built for a [Philips Hue entertainment zone](../../devices/hue.md), where every channel (a bulb, or one segment of a gradient strip) has an x, y, z position from the Hue app, and it runs on WLED strips and matrices by giving them a ring, a line or a grid to stand on.

Where [Party](party.md) and [Light Show](light_show.md) treat the lamps as a list, Orbit treats them as points in space. A gradient strip flows along its length because its segments are at different positions, the two ends of the room can be told apart, and the field can turn in the floor plane or, with the **Plane** setting, up one of the walls, so a room with lamps at different heights turns vertically too.

## How It Works

Orbit works out, once, where every lamp stands: the angle around the centre of the room, the distance from the centre, and the position along any heading. Every frame it evaluates a **mode** at those positions: a colour from the palette (the gradient picker) and a brightness for every lamp.

The continuous modes (swirl, beacon, sectors, wave, ripple, noise, and halves with **Heading Step** at 0) move on their own clock, locked to the beat: one full turn, one wave cycle or one noise drift unit takes **Beats Per Turn** beats of the measured tempo. The stepped modes (sweep, halves, corners, scatter) advance on every step of the [trigger](#trigger).

Lamps that a mode leaves unlit are not simply off: they show their field colour, the palette colour of their place in the room, dimmed to the **Background** level. That keeps the whole room in the picture while the bright part moves through it.

## Modes

| Mode      | What happens                                                                                         |
|-----------|------------------------------------------------------------------------------------------------------|
| `swirl`   | The palette is wrapped around the room by angle and turns. **Sectors** is how many times the palette repeats around the room; **Softness** darkens the trough of every repeat so a bright lobe turns with the colours. With a rainbow palette the whole room is a colour wheel turning. |
| `beacon`  | **Sectors** bright lobes turn around the room, each about half a sector wide with dark gaps between them, like a lighthouse. **Softness** shapes the lobe from a hard block (0) to a triangle (1). The colour field underneath drifts slowly the other way, so a lobe changes colour as it goes round. |
| `sectors` | The palette is cut into **Sectors** wedges (at least 2) that turn as a wheel. **Softness** blends the edges: 0 is a hard step, 1 is a smooth swirl. |
| `wave`    | The palette flows along the **Heading**, from the back of the room to the front at heading 0, from left to right at 90. **Wavelength** is the length of one palette cycle in room lengths; **Softness** darkens the trough of every cycle. |
| `ripple`  | The same by distance from the centre of the room: rings of colour running outward (**Spin** clockwise) or inward (counter). |
| `sweep`   | On every step a new palette colour floods the room: a colour front crosses along the heading over the step, lamps behind it in the new colour, ahead of it in the old one, blended over a front **Softness** wide. **Heading Step** turns the heading per event: 180 flips the direction every time, 90 goes round the four sides, 51 gives seven directions in turn, 0 keeps it fixed. |
| `halves`  | The room is split in two colours along the heading, half a palette apart. With **Heading Step** above 0 the split turns that many degrees per step (90: front/back, then left/right...), at 0 it turns smoothly, one turn per **Beats Per Turn** beats. **Softness** blends across the split up to a full half palette across the room. |
| `corners` | The lamps are grouped into **Sectors** balanced channels around the room (2 = right and left, 4 = the corners, turned by the **Heading**, so 2 with heading 90 is front and back) and every step lights the next channel: clockwise, counter, back and forth (`alternate`) or a random one (`random`, never the same twice). The channel holds, then fades over the **Softness** share of the step. |
| `noise`   | A three dimensional noise field over the lamps, sampled at the x, y and z of every lamp, drifting with time. **Wavelength** is the size of the blobs in room lengths; **Sectors** above 1 terraces the field into that many colour steps, blended by **Softness**; 1 keeps it smooth, like northern lights. |
| `scatter` | Every step picks **Sectors** random cluster centres among the lamps and lights the lamps within the **Radius** of a centre with a soft falloff, one palette colour per cluster, in all three dimensions, then holds and fades over the **Softness** share of the step. |
| `auto`    | Rotates through the modes above, changing every **Auto Steps** steps. With **Auto Sections** on it follows the music: the loud parts get the hard modes (beacon, sectors, sweep, halves, corners, scatter), the quiet parts the soft ones (swirl, wave, ripple, noise), a drop after a quiet build switches the mode at once, and every 9 to 15 seconds the palette shifts, on a bar boundary. |

## Settings

| Setting              | What it does                                                                                       |
|----------------------|----------------------------------------------------------------------------------------------------|
| **Mode**             | See the table above.                                                                               |
| **Layout**           | Where the lamps stand. `Auto` takes the positions from the device when every device of the virtual knows them (a Hue entertainment zone), a grid for a matrix, and a ring otherwise. `Ring`, `Line` and `Grid` force a layout. |
| **Beats Per Turn**   | Beats for one turn of the field, one wave cycle or one noise drift unit (1 to 64). 8 turns the room once per two bars. |
| **Spin**             | `clockwise`, `counter`, `alternate` (reverses after every turn, or every event in the stepped modes) or `random`. For ripple clockwise runs outward and counter inward; for corners it is the order of the channels. |
| **Heading**          | Direction of wave, sweep and halves, and the turn of the corner channels, in degrees: 0 towards the front, 90 towards the right. |
| **Heading Step**     | Degrees the heading turns per event for sweep and halves. 0 keeps the sweep heading fixed and makes the halves turn smoothly. |
| **Sectors**          | Palette repeats for swirl, lobes for beacon, wedges for sectors, channels for corners, clusters for scatter, terraces for noise. Never more than there are lamps. |
| **Softness**         | Trough darkness for swirl, wave and ripple; edge blend for beacon, sectors, halves, sweep and noise; the share of the step over which corners and scatter fade. |
| **Wavelength**       | Length of one palette cycle in room lengths for wave and ripple (4 is a slow tide with a quarter of the palette across the room, 0.25 four cycles), feature size for noise. |
| **Radius**           | Reach of a scatter cluster. The room is normalised to -1..1, so 1 reaches half way across it.       |
| **Plane**            | Which two axes the field turns in when the device knows its positions: `floor` (x and y, seen from above), `front wall` (x and z: the field turns on the wall facing you, 0 is up) or `side wall` (y and z). Synthetic layouts ignore it. |
| **Background**       | Brightness of the field colour on the lamps that are not lit, 0 turns them off.                    |
| **Flash Limit**      | With flash limit on (the default) no lamp can jump to bright more often than about three times a second, whatever the settings. |
| **Zones** (advanced) | Number of lamps to split the output into. 0 is automatic: one per pixel on a lamp based device and on a matrix, 8 blocks on a long strip. |
| **Auto Steps** (advanced) | Steps between mode changes in auto mode.                                                      |
| **Auto Sections** (advanced) | In auto mode, follow the loud, soft and quiet sections of the music, switch on drops and shift the palette every few seconds. Off rotates blindly. |
| **Color Step** (advanced) | How far along the palette the colour moves per event for sweep, halves, corners and scatter. 0 picks random palette colours at least 15% apart. |

## Trigger

**Trigger**, **Steps Per Beat** and **Timer BPM** work as in [Rave](rave.md#trigger). Every step starts an event in the stepped modes, and the measured time between steps sets the beat period the continuous modes turn to, so the room stays in time with the music at any tempo. When no beat is heard for five seconds the timer takes over.

**Lead** (advanced) fires every step up to 0.3 s ahead of the predicted beat, so that slow lamps light on the beat rather than after it. A Hue zone wants about 0.05 to 0.1 s. It only applies to the audio triggers, the timer is left alone.

## Reactive Settings

**Band**, **Reactive Depth** and **Sensitivity** work as in [Party](party.md#reactive-settings): with a reactive depth above 0 the brightness of the whole field follows the level of the chosen band, so quiet passages dim the room and accents bring it back.

```{warning}
Flashing lights, and in particular whole room flashes faster than about three per second, can trigger seizures in people with photosensitive epilepsy. A beacon or sectors mode at one beat per turn on a fast track flashes every lamp several times a second; the flash limit is there for that reason.
```

## Presets

| Preset              | Mode    | Notes                                                                   |
|---------------------|---------|-------------------------------------------------------------------------|
| Tyc Room Spin       | swirl   | A full rainbow turning round the room once per eight beats              |
| Tyc Twin Beacon     | beacon  | Two lobes turning, colours drifting the other way                       |
| Lighthouse Sweep    | beacon  | One soft lobe, one turn per four beats                                  |
| Colour Wheel        | sectors | Four hard palette wedges turning                                        |
| Tide                | wave    | A slow palette tide from the back to the front of the room              |
| Rising Wall         | wave    | The palette rising up the front wall                                    |
| Whirlpool           | ripple  | Rings running into the centre of the room                               |
| Shockwave           | ripple  | Rings bursting out of the centre on the bass                            |
| Flip Flood          | sweep   | A new colour floods the room every beat, from alternating sides         |
| Seven Ways          | sweep   | Colour fronts from seven directions in turn                             |
| Half Turn           | halves  | Two colours, the split turning a quarter every beat                     |
| Corner Chase        | corners | The four corners lit one after the other                                |
| Aurora Field        | noise   | Slow smooth noise in cool colours                                       |
| Terraced Noise      | noise   | Four colour terraces drifting over the room                             |
| Tyc Cluster Scatter | scatter | Three random clusters per beat, anywhere in the room, fading out        |
| Tyc Orbit Autopilot | auto    | Rotates through every mode on a rainbow, a new mode every eight bars    |

## Smart Bulbs

On a Hue entertainment zone every channel is one lamp with its own position, so place the lights carefully in the Hue app: the turning centre is the middle of your placed lights, and the front (angle 0) is the positive y side, the TV wall in the Hue app. Give gradient strips and lightstrips a real length in the app and their segments flow with the field.

Bulbs are slow to change colour and the bridge relays a limited number of updates a second, so the smooth modes look best at 4 to 16 beats per turn; at 1 or 2 beats per turn a beacon becomes a flashing chase and the flash limit starts to hold lamps back. A little **Background** (0.1 to 0.3) keeps the unlit lamps in the room's colour instead of black, which reads much better on bulbs than a hard off.

## Strips And Matrices

A WLED strip that knows no positions is laid around a ring (or along a line, or a grid with the **Layout** setting), split into 8 zones by default, so swirl and beacon run along the strip and a sweep floods it end to end. Set **Zones** higher for a smoother flow. A matrix gets a grid with one lamp per pixel, so a swirl is a turning pinwheel and a ripple is concentric rings.
