# Party effects test plan

This is the checklist for testing the party mode effects on a real room: a
Philips Hue entertainment zone and a WLED strip. The unit tests prove the
maths (which lamp gets which colour at which time); they cannot say whether
the room *feels* right. Everything on this page needs a person in the room
with the music on. Work through it in one session and note the outcome of
every check, the defaults that felt wrong and the values that felt right.

The effects under test are [Disco](../effects/simple/disco.md),
[Party](../effects/simple/party.md), [Light Show](../effects/simple/light_show.md),
[Orbit](../effects/simple/orbit.md) and [True Strobe](../effects/simple/true_strobe.md),
plus the [Hue light orders](../devices/hue.md#light-order) and room positions
they rely on.

```{warning}
Several checks below flash the whole room. Make sure nobody in the room has
photosensitive epilepsy before you start, and keep the strobe checks short.
```

## Before you start

- LedFx runs against the Hue zone that contains bulbs **and** at least one
  gradient strip (segments as separate channels), and against one WLED strip.
- The bridge streams one entertainment area at a time. Make sure no other
  app or automation holds the stream while you test, or LedFx's device stays
  offline.
- The audio input is the one the music actually plays through. In the LedFx
  audio settings check the input device and that the melbank moves with the
  music before judging any effect.
- Put the Hue device's **Light order** on `Along the strips` unless a check
  says otherwise, and note the resulting pixel order (device settings) so
  you can tell which pixel is which lamp.
- Play three kinds of music for every effect: a four to the floor dance
  track around 128 BPM, something with quiet verses and loud drops, and a
  slow acoustic or ambient track. Note per effect which one it suits.
- Record for every check: pass / fail / "works but", the setting values you
  ended on, and one line on how it felt.

## Room positions and light order

These decide whether the spatial effects flow along the strips and turn the
room in the right direction.

| Check | Expect |
|-------|--------|
| Device settings show the channel positions read from the bridge (`pixel_lights`) and the strip members (`pixel_members`). | Every channel has an x, y, z; the gradient strips have one member per segment. |
| Light order `Around the room` with the Rave chase. | The chase runs along the walls clockwise seen from above, front (TV side) after left. If it runs the other way round or jumps, note the room layout in the Hue app. |
| Light order `Along the strips` with the LedFx Gradient effect on a rainbow. | The rainbow runs continuously along each gradient strip in segment order and straight on into the next strip, then over the bulbs. No colour jump inside a strip. |
| Orbit `swirl` (any light order). | The rainbow lies around the room by position, the strip shows a smooth part of it, and the whole field turns. Changing the Light order must not change the picture (Orbit uses positions, not the order). |
| Orbit `wave` with heading 0 then 90. | Heading 0 travels from the back of the room to the front (towards the TV), 90 towards the right wall. If both are mirrored, the Hue app room is mirrored: note it. |
| Orbit `plane` set to `front wall`. | Lamps at different heights (floor lamp vs ceiling) get different colours and the field turns vertically. With all lamps at one height the room shows one colour band: expected. |
| Bridge Pro with SpatialAware positions. | The same checks look at least as good as with hand placed positions. |

## Disco

Hue zone, Light order `Along the strips`, one genre preset at a time.

| Check | Expect |
|-------|--------|
| `Pop` preset, dance track. | Bass lamps thump on the kick, voice lamps follow the vocal, treble lamps twinkle. All three channels visibly different. |
| Sensitivity `0.5` vs `1.0`. | At 0.5 only the clear beats hit, at 1.0 the lamps hit on almost every accent. Note where "too busy" starts. |
| Quiet passage or track pause. | After about two seconds the lamps drift through palette colours, never going dark (with Idle Brightness 1.0). |
| `Peak Strobe` preset. | A white flash on every beat, all lamps together, dark in between, never faster than five a second. |
| `Enter The Void` preset. | Colour glides with the pitch of the music, brightness with the loudness; no jumping. |
| Relaxed presets (`R&B`, `Ambient`). | Lamps stay bright between beats and only dip. |
| Gradient strip. | Each channel of the strip follows its own Disco channel (interleaved), so the strip sparkles rather than flashing as one. Note whether `Blocks` assignment looks better. |

## Party

| Check | Expect |
|-------|--------|
| `Frost Strike` on the beat. | Every beat an icy white flash cooling to blue, in time with the kick, no double triggers. |
| `Domino Run`. | The chase goes round the room once per bar following the walls. |
| `Tyc Room Turn`. | Full rainbow turning round the room, twice a beat, smooth on the strip. |
| `Bass Ring`. | A ring spreading from the centre lamp outwards on the bass, once per bar. |
| `Volume Glow`. | Warm wash that opens with the music level and closes in the quiet parts. |
| `Confetti Burst`. | Random lamps flash on the high accents, never more than about three flashes a second per lamp. |
| Flash Limit off vs on with `Tyc Scatter Strobe`. | With the limit on, no lamp flashes more than about three times a second even at four steps per beat. |
| No beat for five seconds. | The timer takes over at the Timer BPM, the show keeps moving. |
| Spatial families (`Room Chase`, `Centre Ring`, `Front Wash` if present). | Movement follows the room positions: the ring really starts at the room centre, the wash crosses the room along the heading. |

## Light Show

| Check | Expect |
|-------|--------|
| `cycle` pattern, `fade` envelope. | One lamp after another around the light order, each fading over the step. |
| `scatter` and `double scatter`. | Random lamps per step; with grouping `room` no two neighbouring lamps light in one step where the room allows it. |
| `stage` with `stages` 4 and grouping `room`. | The four groups are the four corners of the room. |
| `strobe` envelope at two steps per beat. | Short hard flashes, dark between, no smear on the bulbs. Note if the Hue bulbs smear at four steps per beat. |
| `auto` pattern, envelope and colour mode. | On loud parts hard patterns (strobe, stage), on quiet parts soft ones (fade, glow); a change every `auto_steps` steps. Note if the loud threshold is right for your input level. |
| Backlight at 0.25. | Unlit lamps show the backlight colour dimly, the room never goes black. |
| New envelopes (`peak`, `pulse`, `soft strobe`, `cross fade` ...). | Each looks like its description in the docs; note any that look identical to another on Hue bulbs. |

## Orbit

| Check | Expect |
|-------|--------|
| `Tyc Room Turn` (swirl, 8 beats per turn). | One full turn every two bars, in time with the music; the turn stays locked over a whole track. |
| `beacon` with 1 and 3 lobes. | One (or three) bright lobes sweeping round, soft edges, dark between them. |
| `sectors` with 4 sectors, softness 0 then 0.5. | Hard colour quarters turning; softness blends the edges. |
| `wave` and `ripple`. | A gradient flows across the room / rings run in or out from the centre; the strip shows the gradient within itself. |
| `sweep` with heading step 180. | A new colour crosses the room every step, alternating direction. |
| `halves`. | Two colour halves turning 90 degrees per step. |
| `corners`. | The corners light one after another; with spin `random` in random order. |
| `noise` smooth and terraced. | Slow drifting colour clouds; terraced gives hard colour zones. Never flickers. |
| `scatter`. | Clusters of neighbouring lamps light per step, not single random lamps. |
| Reactive depth 0 vs 0.6. | At 0.6 the whole show dims in quiet parts and comes back on accents. |
| `spin` alternate and counter. | Direction reverses per event / turns the other way. |
| WLED strip (ring fallback). | The strip is split into zones laid out as a ring, so swirl and beacon still turn along the strip. |

## True Strobe

Short checks only.

| Check | Expect |
|-------|--------|
| `Tyc Sync Strobe` (all, 8 Hz, bursts of 4 on the beat). | Four flashes after every beat, every lamp and every strip segment switching in the same instant. Any lamp lagging is a bridge or bulb limit: note which. |
| `Club Strobe` at 10 Hz then rate 12. | Clean on and off at 10 Hz. At 12 note whether the bulbs still show separate flashes or smear into a flicker. |
| `Tyc Rainbow Strobe`. | Every lamp its own palette colour by position, all flashing together. |
| `Confetti Strobe`. | A different random half of the lamps per flash, all switching in the same frame. |
| `Lighthouse Strobe`, `Ping Pong`, `Corner Chase`. | The flash travels round the room / alternates halves / steps corners. |
| `Triple Flash`. | Three flashes then a fade out; the fade is visible on the bulbs. |
| `Bass Gate`. | Strobes only while the bass is loud, silent in breaks. |
| `Slow Pulse` (2 Hz, 100 ms). | The slow all lamps in sync flash feel; compare with what you remember from the phone app. |
| Default on time 0.05 s at 8 Hz. | The pop reaches full brightness on the strips; note whether the bulbs need 0.07 s to look as bright. |
| `Tyc Rainbow Strobe` with background 0.2. | A dim rainbow stays on between the flashes without the flashes looking weaker. |
| Beat bursts with lead 0 then 0.08 (advanced trigger setting). | With the lead the bursts land on the beat on the bulbs instead of just after it. Note the lead that felt right. |
| Change rate or spread while running. | The strobe restarts cleanly with one flash, no lamp stays stuck on. |

## WLED

| Check | Expect |
|-------|--------|
| Disco, Party, Light Show, Orbit on a 150 pixel WLED strip. | The strip is split into 8 zones (or the Zones setting) and every effect behaves as on bulbs, zone by zone. |
| Orbit layout `Line` vs `Ring` on the strip. | Line: waves run along the strip. Ring: swirl turns along the strip and wraps. |
| A WLED matrix virtual with rows set. | Orbit `Auto` layout uses the grid: swirl turns around the matrix centre, wave crosses it along the heading. |

## Results

Copy this table into the report of the test session:

| Effect | Check | Result | Values that felt right | Note |
|--------|-------|--------|------------------------|------|
|        |       |        |                        |      |
