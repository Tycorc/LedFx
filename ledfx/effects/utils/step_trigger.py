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


def step_trigger_schema(trigger="Beat", steps_per_beat="1", timer_bpm=128):
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
    }


class StepTrigger:
    """Decides when the next step is due."""

    # Seconds without an audio trigger before the timer takes over
    SILENCE_TIMEOUT = 5.0
    # Bounds for the measured step interval
    MIN_STEP_INTERVAL = 0.05
    MAX_STEP_INTERVAL = 10.0

    def __init__(self, config, now):
        self.configure(config)
        self.reset(now)

    def configure(self, config):
        """Read trigger, steps_per_beat and timer_bpm from an effect config."""
        self.trigger = config["trigger"]
        self.steps_per_beat = STEP_MAPPINGS[config["steps_per_beat"]]
        self.timer_interval = 60.0 / config["timer_bpm"] / self.steps_per_beat

    def reset(self, now):
        self.pending = False
        self.last_step_time = now
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
            if (
                (beat and self.steps_per_beat >= 1)
                or int(phase) != int(self._last_phase)
                or phase < self._last_phase
            ):
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
        """
        if (
            self.using_timer(now)
            and now - self.last_step_time >= self.timer_interval
        ):
            self.pending = True

        if not self.pending:
            return False

        self.pending = False
        interval = now - self.last_step_time
        if self.MIN_STEP_INTERVAL < interval < self.MAX_STEP_INTERVAL:
            self.step_interval = interval
        self.last_step_time = now
        return True

    def elapsed(self, now):
        """Seconds since the last step."""
        return now - self.last_step_time

    def progress(self, now):
        """Position within the current step, 0 at the step, 1 at the next."""
        return min(1.0, self.elapsed(now) / self.step_interval)
