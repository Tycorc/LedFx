"""Unit tests for the shared step trigger, in particular the lead."""

from types import SimpleNamespace

import pytest
import voluptuous as vol

from ledfx.effects.utils.step_trigger import (
    STEP_MAPPINGS,
    TRIGGERS,
    StepTrigger,
    step_trigger_schema,
)


def config(**overrides):
    schema = vol.Schema(step_trigger_schema())
    return schema(overrides)


def audio(beat=False, phase=0.0, bass=False, onset=False):
    return SimpleNamespace(
        bpm_beat_now=lambda: beat,
        bar_oscillator=lambda: phase,
        volume_beat_now=lambda: bass,
        onset=lambda: onset,
    )


def test_schema_defaults():
    conf = config()
    assert conf["trigger"] == "Beat"
    assert conf["steps_per_beat"] == "1"
    assert conf["timer_bpm"] == 128
    assert conf["lead"] == 0.0
    assert set(STEP_MAPPINGS) == {"1/4", "1/2", "1", "2", "4"}
    assert "Timer" in TRIGGERS
    with pytest.raises(vol.Invalid):
        config(lead=1.0)
    assert vol.Schema(step_trigger_schema(lead=0.08))({})["lead"] == 0.08


def test_timer_steps_at_the_timer_tempo():
    stepper = StepTrigger(config(trigger="Timer", timer_bpm=60), now=0.0)
    assert stepper.poll(0.5) is False
    assert stepper.poll(1.0) is True
    assert stepper.poll(1.5) is False
    assert stepper.poll(2.0) is True
    assert stepper.step_interval == pytest.approx(1.0)
    assert stepper.progress(2.5) == pytest.approx(0.5)


def test_beats_step_the_trigger_and_hand_over_from_the_timer():
    stepper = StepTrigger(config(timer_bpm=60), now=0.0)
    # The timer runs until the first beat is heard
    assert stepper.using_timer(0.0)
    stepper.audio(audio(beat=True, phase=0.0), 0.5)
    assert not stepper.using_timer(0.5)
    assert stepper.poll(0.5) is True
    assert stepper.poll(1.0) is False
    stepper.audio(audio(beat=True, phase=0.0), 1.5)
    assert stepper.poll(1.5) is True
    assert stepper.step_interval == pytest.approx(1.0)


def test_silence_hands_back_to_the_timer():
    stepper = StepTrigger(config(timer_bpm=120), now=0.0)
    stepper.audio(audio(beat=True), 1.0)
    stepper.poll(1.0)
    assert not stepper.using_timer(5.9)
    assert stepper.using_timer(6.0)


def run_beats(stepper, beat_times, end, dt=0.01):
    """Poll every dt, feeding a beat at the given times, returns step times."""
    steps = []
    beats = list(beat_times)
    for i in range(round(end / dt) + 1):
        t = round(i * dt, 6)
        if beats and abs(t - beats[0]) < dt / 2:
            stepper.audio(audio(beat=True, phase=0.0), t)
            beats.pop(0)
        if stepper.poll(t):
            steps.append(round(t, 3))
    return steps


def test_without_a_lead_the_steps_are_the_beats():
    stepper = StepTrigger(config(timer_bpm=60), now=0.0)
    steps = run_beats(stepper, [1.0, 2.0, 3.0, 4.0], 4.5)
    assert steps == [1.0, 2.0, 3.0, 4.0]


def test_lead_fires_the_step_early_and_swallows_the_real_beat():
    stepper = StepTrigger(config(timer_bpm=60, lead=0.1), now=0.0)
    steps = run_beats(stepper, [1.0, 2.0, 3.0, 4.0, 5.0], 5.5)
    # The first beat anchors the prediction (the timer tempo is the first
    # guess of the interval), from then on every step comes 100 ms before
    # its beat, and only once per beat
    assert steps == [1.0, 1.9, 2.9, 3.9, 4.9]


def test_lead_does_not_drift():
    stepper = StepTrigger(config(timer_bpm=60, lead=0.1), now=0.0)
    beats = [float(i) for i in range(1, 12)]
    steps = run_beats(stepper, beats, 11.5)
    assert steps[-1] == pytest.approx(10.9)
    assert stepper.step_interval == pytest.approx(1.0, abs=0.02)


def test_lead_keeps_a_late_beat_as_a_new_step():
    stepper = StepTrigger(config(timer_bpm=60, lead=0.1), now=0.0)
    # The tempo slows: the beat after the early step comes 0.4 s late
    steps = run_beats(stepper, [1.0, 2.0, 3.4], 3.6)
    assert steps == [1.0, 1.9, 2.9, 3.4]


def test_lead_leaves_the_timer_alone():
    stepper = StepTrigger(config(trigger="Timer", timer_bpm=60, lead=0.1), 0.0)
    steps = run_beats(stepper, [], 3.05)
    assert steps == [1.0, 2.0, 3.0]


def test_elapsed_counts_from_the_early_step():
    stepper = StepTrigger(config(timer_bpm=60, lead=0.1), now=0.0)
    run_beats(stepper, [1.0, 2.0, 3.0], 3.0)
    assert stepper.elapsed(3.0) == pytest.approx(0.1)
    assert stepper.progress(3.4) == pytest.approx(0.5, abs=0.02)


def test_sub_beat_steps_follow_the_bar_oscillator():
    stepper = StepTrigger(config(steps_per_beat="2"), now=0.0)
    stepper.audio(audio(beat=True, phase=0.0), 1.0)
    assert stepper.poll(1.0) is True
    stepper.audio(audio(beat=False, phase=0.3), 1.2)
    assert stepper.poll(1.2) is False
    stepper.audio(audio(beat=False, phase=0.6), 1.5)
    assert stepper.poll(1.5) is True


@pytest.mark.parametrize("steps_per_beat", ["1", "2"])
def test_a_late_beat_does_not_double_the_step(steps_per_beat):
    stepper = StepTrigger(config(timer_bpm=120, steps_per_beat=steps_per_beat), now=0.0)
    # The bar oscillator runs on linearly past the next whole beat, which
    # the tracker only reports 20 ms later: that is one step, not two
    frames = [
        (0.50, True, 1.0),
        (0.52, False, 1.04),
        (0.75, False, 1.5),
        (0.98, False, 1.96),
        (1.00, False, 2.0),
        (1.02, True, 2.0),
        (1.04, False, 2.04),
    ]
    steps = []
    for t, beat, phase in frames:
        stepper.audio(audio(beat=beat, phase=phase), t)
        if stepper.poll(t):
            steps.append(t)
    expected = [0.5, 1.02] if steps_per_beat == "1" else [0.5, 0.75, 1.02]
    assert steps == expected


def test_bass_and_onset_triggers():
    stepper = StepTrigger(config(trigger="Bass hit"), now=0.0)
    stepper.audio(audio(bass=True), 1.0)
    assert stepper.poll(1.0) is True
    stepper.audio(audio(beat=True), 1.5)
    assert stepper.poll(1.5) is False
    stepper = StepTrigger(config(trigger="Onset"), now=0.0)
    stepper.audio(audio(onset=True), 1.0)
    assert stepper.poll(1.0) is True


def test_configure_changes_the_timer_interval():
    stepper = StepTrigger(config(trigger="Timer", timer_bpm=60), now=0.0)
    stepper.configure(config(trigger="Timer", timer_bpm=120, lead=0.05))
    assert stepper.timer_interval == pytest.approx(0.5)
    assert stepper.lead == 0.05
    assert stepper.poll(0.5) is True
