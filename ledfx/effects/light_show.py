"""Light Show: pattern based party effects for a room of smart bulbs."""

import timeit

import numpy as np
import voluptuous as vol

from ledfx.color import parse_color, validate_color
from ledfx.effects.audio import AudioReactiveEffect
from ledfx.effects.gradient import GradientEffect
from ledfx.effects.utils.flash_limiter import FlashLimiter
from ledfx.effects.utils.layout import (
    LAYOUTS,
    anchors,
    angles,
    assign_channels,
    normalise,
    resolve_positions,
    zone_map,
    zone_positions,
)
from ledfx.effects.utils.step_trigger import StepTrigger, step_trigger_schema


class LightShowEffect(AudioReactiveEffect, GradientEffect):
    """
    Party patterns in the style of the entertainment effect libraries of
    Hue DJ apps (strobe cycles, scatter fades, stage strobes, fills, sweeps,
    waves, palette loops, backlit variants...).

    Those libraries are dozens of named effects, but every one of them is a
    combination of a few things, which is what this effect exposes:

    - pattern:  which lamps light up on every step
    - envelope: what a lit lamp does during the step (strobe, hold, fade...)
    - colours:  where the lamp colours come from
    - grouping: whether "next", "half" and "opposite" follow the light
      order or the real positions of the lamps in the room
    - backlight: what the lamps that are not lit show
    - trail and rhythm: how long a lamp's envelope outlives its step and
      which steps of a bar actually fire

    Steps are driven by the beat tracker, bass hits, onsets or a timer, see
    StepTrigger. The output is treated as a handful of independent lamps
    (one per pixel on a Hue zone, blocks on a strip) just like Rave. Every
    lamp keeps its own envelope clock, so with a trail longer than one step
    the fades of successive lamps overlap.
    """

    NAME = "Light Show"
    CATEGORY = "BPM"
    HIDDEN_KEYS = ["gradient_roll"]
    ADVANCED_KEYS = AudioReactiveEffect.ADVANCED_KEYS + [
        "zones",
        "layout",
        "color_step",
        "strobe_flashes",
        "flash_length",
        "flare_color",
        "trail",
        "rest_steps",
        "rhythm",
    ]

    PATTERNS = [
        "auto",
        "all",
        "cycle",
        "scatter",
        "double",
        "double scatter",
        "sprinkle",
        "stage",
        "stage fill",
        "fill",
        "scatter fill",
        "paint",
        "scatter paint",
        "sweep",
        "split",
        "flip",
        "chase",
        "ramp",
        "wave",
        "loop",
    ]
    ENVELOPES = [
        "auto",
        "strobe",
        "hold",
        "fade",
        "grow",
        "glow",
        "flare",
        "dip",
        "peak",
        "pulse",
        "cross fade",
        "swell",
    ]
    COLOR_MODES = ["auto", "cycle", "random", "per lamp", "per group"]
    GROUPINGS = ["order", "room"]
    # Which steps fire, meant for four steps per beat so that 16 characters
    # are one bar: x = a step, . = keep the lamps as they are, o = all off
    RHYTHMS = {
        "steady": "x",
        "downbeat": "x...x...x...x.x.",
        "offbeat": "x..x..x...x.x...",
        "chop": "x.o.x.o.x.o.x.o.",
        "half time": "x.x.x...x.x.x...",
        "breaks": "x.o...x.....x...",
        "pairs": "xxoo",
        "sparse": "x.xx.xx..x.xxx..x.xx.xxx..xx.x..",
    }

    # Patterns that light whole groups of lamps (the Stages groups)
    GROUP_PATTERNS = (
        "stage",
        "stage fill",
        "paint",
        "scatter paint",
        "sweep",
        "ramp",
    )
    # Patterns that run in rounds: Rest Steps of darkness follow a round
    ROUND_PATTERNS = (
        "fill",
        "scatter fill",
        "stage fill",
        "paint",
        "scatter paint",
        "sweep",
    )
    # Round patterns whose colour moves once per round, not once per step
    ROUND_COLOR_PATTERNS = ("stage fill", "paint", "scatter paint", "sweep")

    # What auto mode picks from. Loud passages get the harder patterns and
    # envelopes, quiet ones the softer set.
    AUTO_LOUD_PATTERNS = [
        "all",
        "stage",
        "double",
        "split",
        "flip",
        "scatter",
        "double scatter",
        "sprinkle",
        "scatter fill",
        "sweep",
    ]
    AUTO_QUIET_PATTERNS = [
        "cycle",
        "fill",
        "stage fill",
        "paint",
        "chase",
        "ramp",
        "wave",
        "loop",
        "scatter",
        "double",
    ]
    AUTO_LOUD_ENVELOPES = ["strobe", "flare", "fade", "hold", "pulse", "peak"]
    AUTO_QUIET_ENVELOPES = [
        "fade",
        "glow",
        "grow",
        "hold",
        "cross fade",
        "swell",
        "dip",
    ]
    AUTO_COLOR_MODES = ["cycle", "random", "per lamp", "per group"]
    # Filtered lows power above which a passage counts as loud
    AUTO_LOUD_LEVEL = 0.35

    # Minimum distance along the palette between a lamp's old and new
    # colour in random colour mode, so that every step is a visible change
    MIN_PALETTE_STEP = 0.15
    # With at most this many pixels every pixel is treated as its own lamp
    AUTO_ZONE_PIXEL_LIMIT = 32
    # Zone count used for larger outputs (strips, matrices) when zones is 0
    AUTO_ZONE_COUNT = 8
    # Part of the step over which a flare blends from the flare colour to
    # the lamp colour
    FLARE_BLEND = 0.25
    # Brightness levels of the ramp pattern, one per step
    RAMP_LEVELS = (0.0, 0.25, 0.5, 0.75)
    # Parts of the step the peak envelope rises and holds the peak colour;
    # it falls over the same part it rose
    PEAK_RISE = 0.45
    PEAK_HOLD = 0.1
    # A pulse is on for one slot of the step and off for the next one
    PULSE_SLOTS = 8
    # Degrees the swell envelope advances per step: a full swell and dip
    # every 32 steps
    SWELL_STEP_DEGREES = 11.25
    # Lamps closer than this many nearest neighbours count as neighbours
    # for the room grouping of the scatter patterns
    NEIGHBOUR_COUNT = 2

    CONFIG_SCHEMA = vol.Schema(
        {
            vol.Optional(
                "pattern",
                description="Which lamps light up on each step",
                default="cycle",
            ): vol.In(PATTERNS),
            vol.Optional(
                "envelope",
                description="What a lit lamp does during the step",
                default="fade",
            ): vol.In(ENVELOPES),
            vol.Optional(
                "color_mode",
                description="Where lamp colours come from: step along the palette, random palette colours, a fixed palette colour per lamp, or one per group that rotates",
                default="cycle",
            ): vol.In(COLOR_MODES),
            vol.Optional(
                "grouping",
                description="Order: next, half and opposite follow the light order. Room: they follow the positions of the lamps in the room",
                default="order",
            ): vol.In(GROUPINGS),
            **step_trigger_schema(),
            vol.Optional(
                "auto_steps",
                description="Steps between changes when pattern, envelope or colour mode is set to auto",
                default=16,
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=128)),
            vol.Optional(
                "stages",
                description="Groups for the stage, fill, paint, sweep and ramp patterns, lamps for sprinkle and chase, peaks for wave, palette repeats for loop",
                default=3,
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=16)),
            vol.Optional(
                "backlight",
                description="Colour shown by the lamps that are not lit",
                default="#000000",
            ): validate_color,
            vol.Optional(
                "backlight_brightness",
                description="Brightness of the backlight, 0 turns unlit lamps off",
                default=0.25,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "flash_limit",
                description="Never let a lamp jump to bright more than about three times a second",
                default=True,
            ): bool,
            vol.Optional(
                "zones",
                description="Number of lamps / zones to split the output into. 0 = auto (one per pixel for bulbs)",
                default=0,
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=64)),
            vol.Optional(
                "layout",
                description="Where the lamps are for the room grouping. Auto uses the device positions when they are known",
                default="Auto",
            ): vol.In(LAYOUTS),
            vol.Optional(
                "color_step",
                description="How far along the palette the colour moves per step in cycle colour mode. 0 keeps one colour",
                default=0.25,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "strobe_flashes",
                description="Flashes per step for the strobe envelope, pulses per step for the pulse envelope",
                default=1,
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=8)),
            vol.Optional(
                "flash_length",
                description="Longest a strobe flash stays on, in seconds",
                default=0.05,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.02, max=0.3)),
            vol.Optional(
                "flare_color",
                description="Colour a flare starts from and the colour of the peak of the peak envelope",
                default="#FFFFFF",
            ): validate_color,
            vol.Optional(
                "trail",
                description="Steps a lamp's envelope keeps running after its step. Above 1 the fades of successive lamps overlap",
                default=1,
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=16)),
            vol.Optional(
                "rest_steps",
                description="Dark steps after every round of the fill, paint and sweep patterns",
                default=0,
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=16)),
            vol.Optional(
                "rhythm",
                description="Which steps of a bar fire, at four steps per beat. Steady fires on every step",
                default="steady",
            ): vol.In(list(RHYTHMS.keys())),
        }
    )

    def on_activate(self, pixel_count):
        now = timeit.default_timer()
        self._rng = np.random.default_rng()
        self._stepper = StepTrigger(self._config, now)
        self._step_count = 0
        self._color_point = self._rng.random()
        self._energy = 0.0
        self._zone_points = None
        self._zone_colors = None
        self._prev_colors = None
        self._last_set = np.zeros(0, dtype=int)
        self._auto_pick()
        self._build_zones(pixel_count)
        self._reset_pattern_state()
        self._limiter = FlashLimiter(self._zone_count, self.flash_limit)
        self._step(now)

    def config_updated(self, config):
        old_pattern = getattr(self, "_applied_pattern", None)
        self._applied_pattern = self._config["pattern"]
        auto_key = (
            self._config["pattern"],
            self._config["envelope"],
            self._config["color_mode"],
        )
        # A setting on auto keeps its current choice through unrelated
        # config changes, the next choice comes with the next auto step
        repick = getattr(self, "_auto_key", None) != auto_key
        if repick or getattr(self, "pixels", None) is None:
            self.pattern, self.envelope, self.color_mode = auto_key
        self._auto_key = auto_key
        self.grouping = self._config["grouping"]
        self.layout = self._config["layout"]
        self.auto_steps = self._config["auto_steps"]
        self.stages = self._config["stages"]
        if getattr(self, "_energy_filter", None) is None:
            self._energy_filter = self.create_filter(
                alpha_decay=0.02, alpha_rise=0.1
            )
        self.color_step = self._config["color_step"]
        self.strobe_flashes = self._config["strobe_flashes"]
        self.flash_length = self._config["flash_length"]
        self.flash_limit = self._config["flash_limit"]
        self.trail = self._config["trail"]
        self.rest_steps = self._config["rest_steps"]
        self.rhythm = self.RHYTHMS[self._config["rhythm"]]
        self.backlight = (
            np.array(parse_color(self._config["backlight"]), dtype=float)
            * self._config["backlight_brightness"]
        )
        self.flare_color = np.array(
            parse_color(self._config["flare_color"]), dtype=float
        )
        if getattr(self, "_stepper", None) is not None:
            self._stepper.configure(self._config)
        if getattr(self, "pixels", None) is not None:
            if repick:
                self._auto_pick()
            self._build_zones(self.pixel_count)
            if (
                len(self._lit_now) != self._zone_count
                or old_pattern != self._config["pattern"]
            ):
                # The lamp count or the pattern changed, start over
                self._reset_pattern_state()
            self._limiter.enabled = self.flash_limit
            self._recolor_static()

    def _reset_pattern_state(self):
        """Forget which lamps are lit and where every pattern was."""
        n = self._zone_count
        self._cursor = -1
        self._stage = -1
        self._split_side = 1
        self._ramp_step = -1
        self._chase_block = np.zeros(0, dtype=int)
        self._round_order = None
        self._round_pos = 0
        self._rest_left = 0
        self._blank = False
        self._lit_now = np.zeros(n, dtype=bool)
        self._lit = np.zeros(n, dtype=bool)
        self._lit_time = np.full(n, -np.inf)
        self._lit_duration = np.ones(n)
        self._lit_step = np.zeros(n, dtype=int)
        self._scale = np.ones(n)

    # ----------------------------------------------------------------- auto

    def _auto_choice(self, options, current):
        """A random option, never the current one when there is a choice."""
        options = [option for option in options if option != current]
        if not options:
            return current
        return options[int(self._rng.integers(len(options)))]

    def _auto_pick(self):
        """Resolve every setting on auto to a concrete value."""
        loud = self._energy >= self.AUTO_LOUD_LEVEL
        if self._config["pattern"] == "auto":
            options = (
                self.AUTO_LOUD_PATTERNS if loud else self.AUTO_QUIET_PATTERNS
            )
            self.pattern = self._auto_choice(options, self.pattern)
            if getattr(self, "_lit", None) is not None:
                self._reset_pattern_state()
        if self._config["envelope"] == "auto":
            options = (
                self.AUTO_LOUD_ENVELOPES if loud else self.AUTO_QUIET_ENVELOPES
            )
            self.envelope = self._auto_choice(options, self.envelope)
        if self._config["color_mode"] == "auto":
            self.color_mode = self._auto_choice(
                self.AUTO_COLOR_MODES, self.color_mode
            )
            self._recolor_static()

    @property
    def on_auto(self):
        return "auto" in (
            self._config["pattern"],
            self._config["envelope"],
            self._config["color_mode"],
        )

    # ---------------------------------------------------------------- zones

    def _build_zones(self, pixel_count):
        """Map pixels onto lamps, keeping the colours of lamps that survive."""
        self._zone_count, self._zone_of_pixel = zone_map(
            pixel_count,
            self._config["zones"],
            self.AUTO_ZONE_PIXEL_LIMIT,
            self.AUTO_ZONE_COUNT,
        )
        zones = self._zone_count

        points = np.zeros(zones)
        colors = np.zeros((zones, 3))
        old_points = self._zone_points
        kept = 0
        if old_points is not None:
            kept = min(len(old_points), zones)
            points[:kept] = old_points[:kept]
            colors[:kept] = self._zone_colors[:kept]
        if zones > kept:
            points[kept:] = self._rng.random(zones - kept)
            colors[kept:] = self._palette(points[kept:])

        self._zone_points = points
        self._zone_colors = colors
        self._prev_colors = colors.copy()
        self._build_room(pixel_count)
        self._recolor_static()

    def _group_anchors(self, count):
        """Anchor points for count groups: 2 are front and back."""
        if count == 2:
            return np.array([[0.0, 1.0, 0.0], [0.0, -1.0, 0.0]])
        return anchors(count)

    def _build_room(self, pixel_count):
        """
        Work out the walk order, groups, halves, opposites and neighbours
        of the lamps, from the light order or from the room positions.
        """
        n = self._zone_count
        groups = max(1, min(self.stages, n))
        index = np.arange(n)
        self._walk = index.copy()
        self._rank = index.copy()
        self._group = index % groups
        self._side = (index >= (n + 1) // 2).astype(int)
        self._opposite = (index + n // 2) % n
        self._near = None
        self._position_source = "order"
        if self.grouping != "room":
            return

        positions, source = resolve_positions(
            self.layout, pixel_count, self._virtual, self._ledfx
        )
        lamps = normalise(zone_positions(positions, self._zone_of_pixel, n))
        self._position_source = source
        if source == "line":
            key = lamps[:, 0]
        else:
            # A lamp exactly at the front may come out a hair before a
            # full turn once the positions are centred: keep it first
            key = np.mod(angles(lamps) + 1e-6, 1.0)
        walk = np.lexsort((index, key))
        self._walk = walk
        self._rank[walk] = index
        self._group = assign_channels(lamps, self._group_anchors(groups))
        self._side = assign_channels(lamps, anchors(2))

        if n > 1:
            if source == "line":
                # The mirror image of every lamp about the centre
                mirror = np.abs(key[:, None] + key[None, :])
            else:
                # Half a turn away around the room
                turn = np.mod(key[:, None] - key[None, :], 1.0)
                mirror = np.abs(turn - 0.5)
            np.fill_diagonal(mirror, np.inf)
            self._opposite = np.argmin(mirror, axis=1)

        neighbours = min(self.NEIGHBOUR_COUNT, max(0, (n - 1) // 2))
        if neighbours > 0:
            distance = np.linalg.norm(
                lamps[:, None, :] - lamps[None, :, :], axis=2
            )
            np.fill_diagonal(distance, np.inf)
            near = np.zeros((n, n), dtype=bool)
            closest = np.argsort(distance, axis=1)[:, :neighbours]
            near[index[:, None], closest] = True
            self._near = near

    def _palette(self, points):
        """Look up palette colours, shape (N, 3), for points in [0, 1]."""
        return self.get_gradient_color_vectorized1d(
            np.asarray(points, dtype=float) % 1.0
        )

    def _lamp_positions(self):
        """Position of every lamp along the walk, the centre of its slot."""
        return (self._rank + 0.5) / self._zone_count

    def _group_points(self):
        """Palette position of every lamp from its group, rotating per step."""
        groups = int(self._group.max()) + 1
        return ((self._group + self._step_count) % groups + 0.5) / groups

    def _recolor_static(self):
        """Apply the colour modes that do not depend on the lit lamps."""
        if self._zone_points is None:
            return
        if self.color_mode == "per lamp":
            self._zone_points = self._lamp_positions()
        elif self.color_mode == "per group":
            self._zone_points = self._group_points()
        else:
            return
        self._zone_colors = self._palette(self._zone_points)

    def _next_points(self, points):
        """Move each point along the palette by a random, clearly visible amount."""
        shift = self._rng.uniform(
            self.MIN_PALETTE_STEP,
            1.0 - self.MIN_PALETTE_STEP,
            size=len(points),
        )
        return (points + shift) % 1.0

    # ---------------------------------------------------------------- steps

    def _random_lamp(self, exclude=None, avoid=(), spread_from=()):
        """
        A random lamp other than exclude and the lamps in avoid.

        With the room grouping the neighbours of exclude and of every lamp
        in spread_from are avoided too, as long as that leaves a choice.
        """
        n = self._zone_count
        if n == 1:
            return 0
        if exclude is not None and exclude < 0:
            # Nothing has been picked yet
            exclude = None
        pool = np.ones(n, dtype=bool)
        if exclude is not None:
            pool[exclude % n] = False
        for lamp in avoid:
            pool[lamp] = False
        if not pool.any():
            pool[:] = True
            if exclude is not None:
                pool[exclude % n] = False
        if self._near is not None:
            spread = pool.copy()
            if exclude is not None:
                spread &= ~self._near[exclude % n]
            for lamp in spread_from:
                spread &= ~self._near[lamp]
            if spread.any():
                pool = spread
        choices = np.flatnonzero(pool)
        return int(choices[self._rng.integers(len(choices))])

    def _group_members(self, group):
        return np.flatnonzero(self._group == group)

    def _round_units(self, pattern):
        """The order in which a round lights its units (lamps or groups)."""
        if pattern in ("fill",):
            return self._walk.copy()
        if pattern == "scatter fill":
            return self._rng.permutation(self._zone_count)
        groups = int(self._group.max()) + 1
        if pattern == "scatter paint":
            return self._rng.permutation(groups)
        return np.arange(groups)

    def _round_step(self, pattern, active):
        """
        Advance a round based pattern by one step.

        fill patterns add one unit per step until every unit is lit and
        then start over, paint patterns never clear (the next round paints
        over the old colours), sweep adds every unit and then removes them
        in the same order. Rest Steps of darkness follow every round.
        Returns True on the first step of a round.
        """
        by_group = pattern in self.GROUP_PATTERNS
        if self._rest_left > 0:
            self._rest_left -= 1
            self._lit[:] = False
            self._lit_time[:] = -np.inf
            return False

        new_round = False
        if self._round_order is None:
            self._round_order = self._round_units(pattern)
            self._round_pos = 0
            new_round = True
            if pattern not in ("paint", "scatter paint"):
                self._lit[:] = False
                self._lit_time[:] = -np.inf
        order = self._round_order
        length = len(order)
        position = self._round_pos

        if pattern == "sweep" and position >= length:
            unit = order[position - length]
            lamps = self._group_members(unit) if by_group else [unit]
            self._lit[lamps] = False
            self._lit_time[lamps] = -np.inf
        else:
            unit = order[position]
            lamps = self._group_members(unit) if by_group else [unit]
            self._lit[lamps] = True
            active[lamps] = True

        self._round_pos = position + 1
        finished = self._round_pos >= (
            2 * length if pattern == "sweep" else length
        )
        if finished:
            self._round_order = None
            self._rest_left = self.rest_steps
        return new_round

    def _pick_lamps(self):
        """
        Choose the lamps of this step.

        Returns the mask of lit lamps, the mask of lamps that take a new
        colour and whether the cycle colour moves on this step.
        """
        n = self._zone_count
        pattern = self.pattern
        active = np.zeros(n, dtype=bool)
        recolor = None
        advance = True
        self._scale[:] = 1.0

        if pattern in ("all", "wave", "loop"):
            active[:] = True

        elif pattern == "cycle":
            self._cursor = (self._cursor + 1) % n
            active[self._walk[self._cursor]] = True

        elif pattern == "scatter":
            self._cursor = self._random_lamp(exclude=self._cursor)
            active[self._cursor] = True

        elif pattern == "double":
            self._cursor = (self._cursor + 1) % n
            lamp = self._walk[self._cursor]
            active[lamp] = True
            active[self._opposite[lamp]] = True

        elif pattern == "double scatter":
            first = self._random_lamp(exclude=self._cursor)
            active[first] = True
            active[self._random_lamp(exclude=first, spread_from=(first,))] = (
                True
            )
            self._cursor = first

        elif pattern == "sprinkle":
            count = max(1, min(self.stages, n))
            chosen = []
            for _ in range(count):
                if chosen:
                    avoid = chosen
                elif n > count:
                    # Start away from the last set so the room changes
                    avoid = self._last_set
                else:
                    avoid = ()
                chosen.append(
                    self._random_lamp(avoid=avoid, spread_from=chosen)
                )
            self._last_set = np.array(chosen, dtype=int)
            active[chosen] = True

        elif pattern == "stage":
            groups = int(self._group.max()) + 1
            self._stage = (self._stage + 1) % groups
            active[self._group == self._stage] = True

        elif pattern in self.ROUND_PATTERNS:
            new_round = self._round_step(pattern, active)
            if pattern in self.ROUND_COLOR_PATTERNS:
                advance = new_round

        elif pattern == "split":
            self._split_side ^= 1
            active[self._side == self._split_side] = True
            if n == 1:
                active[0] = True

        elif pattern == "flip":
            self._split_side ^= 1
            active[self._rank % 2 == self._split_side] = True
            if n == 1:
                active[0] = True

        elif pattern == "chase":
            count = max(1, min(self.stages, n))
            self._cursor = (self._cursor + 1) % n
            block = self._walk[(self._cursor + np.arange(count)) % n]
            self._chase_block = block
            active[block] = True

        elif pattern == "ramp":
            levels = len(self.RAMP_LEVELS)
            self._ramp_step = (self._ramp_step + 1) % levels
            if self._ramp_step == 0:
                groups = int(self._group.max()) + 1
                self._stage = (self._stage + 1) % groups
            active[self._group == self._stage] = True
            self._scale[active] = self.RAMP_LEVELS[self._ramp_step]
            if self._ramp_step != 0:
                recolor = np.zeros(n, dtype=bool)
                advance = False

        if recolor is None:
            recolor = active
        return active, recolor, advance

    def _rhythm_gap(self, index):
        """Steps from the step at index to the next firing step."""
        rhythm = self.rhythm
        length = len(rhythm)
        for gap in range(1, length + 1):
            if rhythm[(index + gap) % length] == "x":
                return gap
        return length

    def _step(self, now):
        """Advance the pattern by one step."""
        self._step_count += 1
        if self.on_auto and self._step_count % self.auto_steps == 0:
            self._auto_pick()

        index = (self._step_count - 1) % len(self.rhythm)
        gate = self.rhythm[index]
        if gate == ".":
            return
        if gate == "o":
            self._lit_now[:] = False
            self._lit_time[:] = -np.inf
            self._blank = True
            return
        self._blank = False

        never_lit = ~np.isfinite(self._lit_time)
        active, recolor, advance = self._pick_lamps()
        self._lit_now = active
        gap = self._rhythm_gap(index)
        self._lit_time[active] = now
        self._lit_duration[active] = (
            self._stepper.step_interval * self.trail * gap
        )
        self._lit_step[active] = self._step_count

        self._prev_colors = self._zone_colors.copy()
        mode = self.color_mode
        if mode == "cycle":
            if advance:
                self._color_point = (self._color_point + self.color_step) % 1.0
            # Lamps that were never lit take the colour too, so a room
            # that is shown lit (dip, paint) starts out uniform
            targets = recolor | never_lit
            self._zone_points[targets] = self._color_point
            self._zone_colors[targets] = self._palette([self._color_point])[0]
        elif mode == "random":
            self._zone_points[recolor] = self._next_points(
                self._zone_points[recolor]
            )
            self._zone_colors[recolor] = self._palette(
                self._zone_points[recolor]
            )
        elif mode == "per lamp":
            positions = self._lamp_positions()
            if self.pattern == "loop":
                # The palette walks along the lamps one lamp per step and
                # repeats `stages` times across the room
                positions = (
                    (self._rank + 0.5 + self._step_count)
                    * self.stages
                    / self._zone_count
                )
            elif self.pattern == "chase" and len(self._chase_block):
                # The block carries the whole palette with it
                block = self._chase_block
                positions = positions.copy()
                positions[block] = (np.arange(len(block)) + 0.5) / len(block)
            self._zone_points = positions % 1.0
            self._zone_colors = self._palette(self._zone_points)
        elif mode == "per group":
            self._zone_points = self._group_points()
            self._zone_colors = self._palette(self._zone_points)

    # ------------------------------------------------------------- envelope

    def _envelope_levels(self, progress, elapsed, duration, active):
        """Brightness of every lamp from its own envelope clock."""
        envelope = self.envelope
        n = self._zone_count
        levels = np.zeros(n)
        if not active.any():
            return levels
        p = progress[active]

        if envelope == "strobe":
            period = duration[active] / self.strobe_flashes
            on_time = np.minimum(self.flash_length, period * 0.5)
            within = elapsed[active] < duration[active]
            level = ((elapsed[active] % period) < on_time) & within
            levels[active] = level.astype(float)
        elif envelope in ("hold", "cross fade"):
            levels[active] = 1.0
        elif envelope == "fade":
            levels[active] = 1.0 - p
        elif envelope == "grow":
            levels[active] = p
        elif envelope == "glow":
            levels[active] = np.sin(np.pi * p)
        elif envelope == "flare":
            levels[active] = 1.0 - 0.7 * p
        elif envelope == "dip":
            levels[active] = 1.0 - p
        elif envelope == "peak":
            rise = self.PEAK_RISE
            hold = self.PEAK_HOLD
            levels[active] = np.select(
                [p < rise, p < rise + hold, p < 1.0],
                [p / rise, 1.0, (1.0 - p) / rise],
                0.0,
            )
        elif envelope == "pulse":
            slot = np.floor(p * self.PULSE_SLOTS).astype(int)
            on = (slot % 2 == 0) & (slot < 2 * self.strobe_flashes) & (p < 1)
            levels[active] = on.astype(float)
        elif envelope == "swell":
            phase = np.radians(
                self._lit_step[active] * self.SWELL_STEP_DEGREES
            )
            levels[active] = 0.5 + 0.5 * np.sin(phase)
        else:
            levels[active] = 1.0
        return levels

    def audio_data_updated(self, data):
        self._stepper.audio(data, timeit.default_timer())
        if self.on_auto:
            lows = data.lows_power()
            self._energy = float(self._energy_filter.update(float(lows)))

    def render(self):
        now = self.now
        stepper = self._stepper

        if stepper.poll(now):
            self._step(now)

        elapsed = now - self._lit_time
        duration = self._lit_duration
        with np.errstate(invalid="ignore", divide="ignore"):
            progress = np.clip(elapsed / duration, 0.0, 1.0)
        progress = np.nan_to_num(progress, nan=1.0, posinf=1.0)
        # A lamp lit by the current step never expires before the next
        # one, whatever the measured interval does
        active = (elapsed < duration) | self._lit_now
        levels = self._envelope_levels(progress, elapsed, duration, active)
        levels *= self._scale

        colors = self._zone_colors
        envelope = self.envelope
        if envelope == "flare":
            blend = np.clip(progress / self.FLARE_BLEND, 0.0, 1.0)[:, None]
            colors = self.flare_color * (1.0 - blend) + colors * blend
        elif envelope == "peak":
            at_peak = (
                active
                & (progress >= self.PEAK_RISE)
                & (progress < self.PEAK_RISE + self.PEAK_HOLD)
            )
            colors = np.where(at_peak[:, None], self.flare_color, colors)
        elif envelope == "cross fade":
            colors = self._prev_colors + (colors - self._prev_colors) * (
                progress[:, None]
            )

        if self.pattern in self.ROUND_PATTERNS and not self._blank:
            # Lamps filled by earlier steps stay on at full
            levels[self._lit & ~active] = 1.0
        if self.pattern == "wave":
            phase = self._step_count + progress
            wave = 0.5 + 0.5 * np.sin(
                2.0 * np.pi * (self.stages * self._lamp_positions() - phase)
            )
            levels *= wave

        if envelope == "dip":
            # The room stays on in the lamp colours and the lit lamps dip
            # out to black
            bright = np.ones(self._zone_count)
            bright[active] = levels[active]
            bright = self._limiter.apply(bright, now)
            self.pixels[:] = (colors * bright[:, None])[self._zone_of_pixel]
            return

        levels = self._limiter.apply(levels, now)
        # Every lamp starts on the backlight and the lit lamps blend
        # towards their colour by their level
        lamp_pixels = self.backlight * (1.0 - levels)[:, None] + colors * (
            levels[:, None]
        )
        self.pixels[:] = lamp_pixels[self._zone_of_pixel]
