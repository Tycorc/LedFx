"""
Beat, hit and timer stepping shared by the party mode effects.

A StepTrigger turns the audio analysis into discrete "steps": one step per
beat (or a fraction or multiple of a beat), one per bass hit, one per
onset, or one per timer tick. When no audio trigger has fired for a while
the timer takes over so the lights keep moving between tracks and without
any audio at all.
"""

import voluptuous as vol

TRIGGERS = ["Beat", "Bass hit", "Onset", "Timer"]

STEP_MAPPINGS = {
    "1/4": 0.25,
    "1/2": 0.5,
    "1": 1.0,
    "2": 2.0,
    "4": 4.0,
}


def step_trigger_schema(trigger="Beat", steps_per_beat="1", timer_bpm=128, lead=0.0):
    """Schema entries for the trigger settings, with the given defaults."""
    return {
        vol.Optional(
            "trigger",
            description="What advances the pattern. Timer takes over automatically when no beat is heard",
            default=trigger,
        ): vol.In(TRIGGERS),
        vol.Optional(
            "steps_per_beat",
            description="Steps per beat (below 1 = one step every few beats)",
            default=steps_per_beat,
        ): vol.In(list(STEP_MAPPINGS.keys())),
        vol.Optional(
            "timer_bpm",
            description="Tempo for the Timer trigger, also used while no beat is heard",
            default=timer_bpm,
        ): vol.All(vol.Coerce(int), vol.Range(min=20, max=300)),
        vol.Optional(
            "lead",
            description="Seconds the steps fire ahead of the beat to cover the lag of slow lamps, about 0.05 to 0.1 for a Hue bridge",
            default=lead,
        ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=0.3)),
    }


class StepTrigger:
    """Decides when the next step is due."""

    # Seconds without an audio trigger before the timer takes over
    SILENCE_TIMEOUT = 5.0
    # Bounds for the measured step interval
    MIN_STEP_INTERVAL = 0.05
    MAX_STEP_INTERVAL = 10.0
    # A real step that arrives this long after its early copy, beyond the
    # lead itself, still counts as the same step
    LEAD_TOLERANCE = 0.1

    def __init__(self, config, now):
        self.configure(config)
        self.reset(now)

    def configure(self, config):
        """Read trigger, steps_per_beat and timer_bpm from an effect config."""
        self.trigger = config["trigger"]
        self.steps_per_beat = STEP_MAPPINGS[config["steps_per_beat"]]
        self.timer_interval = 60.0 / config["timer_bpm"] / self.steps_per_beat
        # Seconds the steps fire ahead of the predicted beat, so that slow
        # lamps light on the beat rather than after it
        self.lead = max(0.0, float(config.get("lead", 0.0)))

    def reset(self, now):
        self.pending = False
        self.last_step_time = now
        # Time of the last real (audio or timer) step, the reference for
        # the interval measurement and the early prediction
        self._anchor = now
        self._early_fired = False
        # Measured time between the last two steps, used for envelopes
        self.step_interval = self.timer_interval
        # Start with the timer running so the lights move straight away,
        # the first real beat hands control over to the audio trigger.
        self.last_audio_trigger = now - self.SILENCE_TIMEOUT
        self._last_phase = 0.0

    def using_timer(self, now):
        return (
            self.trigger == "Timer"
            or now - self.last_audio_trigger >= self.SILENCE_TIMEOUT
        )

    def audio(self, data, now):
        """Feed an audio analysis update, call from audio_data_updated."""
        trigger = self.trigger
        if trigger == "Timer":
            return

        if trigger == "Beat":
            beat = data.bpm_beat_now()
            if beat:
                self.last_audio_trigger = now
            if now - self.last_audio_trigger > self.SILENCE_TIMEOUT:
                # Nothing to lock onto, the timer takes over in poll()
                return
            # Quantise the bar oscillator into steps so sub beat and multi
            # beat rates stay in time with the music. A detected beat is
            # always a step boundary at one or more steps per beat.
            phase = data.bar_oscillator() * self.steps_per_beat
            crossed = int(phase) != int(self._last_phase) or phase < self._last_phase
            if crossed and self.steps_per_beat >= 1:
                # The oscillator runs on past the next whole beat when the
                # tracker reports that beat late, so whole beat boundaries
                # are the beat's own: counting the crossing as well would
                # fire the step twice
                crossed = int(phase) % round(self.steps_per_beat) != 0
            if (beat and self.steps_per_beat >= 1) or crossed:
                self.pending = True
            self._last_phase = phase

        elif trigger == "Bass hit":
            if data.volume_beat_now():
                self.last_audio_trigger = now
                self.pending = True

        elif trigger == "Onset":
            if data.onset():
                self.last_audio_trigger = now
                self.pending = True

    def poll(self, now):
        """
        Return True once for every due step, call from render.

        Records the step time and the measured interval between steps.
        With a lead, an audio step is played early, at the predicted time
        of the next step minus the lead, and the real step that follows
        within the lead is swallowed (it still re-anchors the prediction).
        """
        timer = self.using_timer(now)
        if timer and now - self.last_step_time >= self.timer_interval:
            self.pending = True
            self._early_fired = False

        if (
            not timer
            and not self.pending
            and self.lead > 0
            and not self._early_fired
            and now >= self._anchor + self.step_interval - self.lead
            and now - self.last_step_time >= self.MIN_STEP_INTERVAL
        ):
            self._early_fired = True
            self.last_step_time = now
            return True

        if not self.pending:
            return False

        self.pending = False
        interval = now - self._anchor
        if self.MIN_STEP_INTERVAL < interval < self.MAX_STEP_INTERVAL:
            self.step_interval = interval
        self._anchor = now
        if self._early_fired and not timer:
            self._early_fired = False
            if now - self.last_step_time <= self.lead + self.LEAD_TOLERANCE:
                # Already played early
                return False
        self.last_step_time = now
        return True

    def elapsed(self, now):
        """Seconds since the last step."""
        return now - self.last_step_time

    def beat_period(self):
        """Seconds per beat from the measured step interval, at least 0.05."""
        return max(0.05, self.step_interval * self.steps_per_beat)

    def progress(self, now):
        """Position within the current step, 0 at the step, 1 at the next."""
        return min(1.0, self.elapsed(now) / self.step_interval)
