"""Unit tests for the section detector shared by the party mode effects."""

import itertools

import pytest

from ledfx.effects.utils.sections import SECTIONS, SectionDetector

DT = 0.02


def feed(detector, raw, seconds, start, bar_phase=None):
    """Feed a constant level for a while, returns the end time."""
    t = start
    steps = round(seconds / DT)
    for _ in range(steps):
        t += DT
        detector.update(raw, t, bar_phase)
    return t


def test_starts_quiet_and_goes_loud_on_music():
    detector = SectionDetector(now=0.0, seed=1)
    assert detector.section == "quiet"
    t = feed(detector, 0.6, 3.0, 0.0)
    assert detector.section == "loud"
    assert detector.level > 0.9
    assert t == pytest.approx(3.0)


def test_auto_gain_normalises_a_quiet_recording():
    detector = SectionDetector(now=0.0, seed=1)
    # A recording that never gets above 0.1 still counts as loud once the
    # peak has adapted to it
    feed(detector, 0.1, 3.0, 0.0)
    assert detector.section == "loud"


def test_auto_gain_forgets_an_old_peak():
    detector = SectionDetector(now=0.0, seed=1)
    t = feed(detector, 1.0, 3.0, 0.0)
    # Half the old peak is soft at first, but after the peak has decayed
    # for a while it counts as loud again
    t = feed(detector, 0.3, 4.0, t)
    assert detector.section == "soft"
    feed(detector, 0.3, 30.0, t)
    assert detector.section == "loud"


def test_sections_follow_the_level_with_a_minimum_length():
    detector = SectionDetector(now=0.0, seed=1)
    t = feed(detector, 1.0, 3.0, 0.0)
    assert detector.section == "loud"
    # Dropping to a third of the peak gives a soft section, but only once
    # the loud section has lasted its minimum
    t2 = feed(detector, 0.3, 1.0, t)
    assert detector.section == "loud"
    t3 = feed(detector, 0.3, 4.0, t2)
    assert detector.section == "soft"
    feed(detector, 0.0, 6.0, t3)
    assert detector.section == "quiet"


def test_hysteresis_holds_a_section_near_its_threshold():
    detector = SectionDetector(now=0.0, seed=1)
    # Freeze the automatic gain so only the hysteresis is under test
    detector.PEAK_DECAY = 1e9
    # Establish the peak at 1.0, then sit just under the loud threshold
    t = feed(detector, 1.0, 3.0, 0.0)
    assert detector.section == "loud"
    t = feed(detector, 0.53, 6.0, t)
    assert detector.section == "loud"
    t = feed(detector, 0.45, 6.0, t)
    assert detector.section == "soft"
    # Inside the hysteresis band a soft section stays soft, where a loud
    # one stayed loud above
    feed(detector, 0.52, 6.0, t)
    assert detector.section == "soft"
    # But clearly loud goes loud again
    feed(detector, 0.9, 3.0, t + 6.0)
    assert detector.section == "loud"


def test_changed_flags_the_frame_of_a_section_change():
    detector = SectionDetector(now=0.0, seed=1)
    changes = 0
    t = 0.0
    for _ in range(int(3.0 / DT)):
        t += DT
        detector.update(0.8, t)
        changes += detector.changed
    assert changes == 1
    assert detector.time_in_section(t) < 3.0


def test_drop_after_a_quiet_build():
    detector = SectionDetector(now=0.0, seed=1)
    feed(detector, 1.0, 3.0, 0.0)
    t = feed(detector, 0.05, 6.0, 3.0)
    assert detector.section == "quiet"
    drops = 0
    for _ in range(10):
        t += DT
        detector.update(1.0, t)
        drops += detector.drop
    assert drops == 1
    # The drop switches to loud at once, no minimum section wait
    assert detector.section == "loud"


def test_no_drop_while_the_music_stays_loud():
    detector = SectionDetector(now=0.0, seed=1)
    drops = 0
    t = 0.0
    for _ in range(int(10.0 / DT)):
        t += DT
        detector.update(1.0, t)
        drops += detector.drop
    assert drops == 0


def test_palette_changes_every_interval_without_a_bar():
    detector = SectionDetector(now=0.0, palette_interval=10.0, seed=3)
    changes = []
    t = 0.0
    for _ in range(int(60.0 / DT)):
        t += DT
        detector.update(0.5, t)
        if detector.palette_changed:
            changes.append(t)
    assert 4 <= len(changes) <= 8
    gaps = [b - a for a, b in itertools.pairwise(changes)]
    assert all(7.5 - DT <= gap <= 12.5 + DT for gap in gaps)
    assert 0.0 <= detector.palette_offset < 1.0


def test_palette_changes_land_on_a_bar_boundary():
    detector = SectionDetector(now=0.0, palette_interval=5.0, seed=3)
    t = 0.0
    change_phases = []
    # A 4 beat bar oscillator at 2 s per bar
    while t < 30.0:
        t += DT
        phase = (t % 2.0) / 2.0 * 4.0
        detector.update(0.5, t, bar_phase=phase)
        if detector.palette_changed:
            change_phases.append(phase)
    assert change_phases
    assert all(phase < 0.1 for phase in change_phases)


def test_palette_change_gives_up_waiting_for_a_bar():
    detector = SectionDetector(now=0.0, palette_interval=5.0, seed=3)
    t = 0.0
    changed_at = None
    # The bar phase never wraps
    while t < 20.0 and changed_at is None:
        t += DT
        detector.update(0.5, t, bar_phase=1.0)
        if detector.palette_changed:
            changed_at = t
    assert changed_at is not None
    assert changed_at <= 5.0 * 1.25 + detector.BAR_WAIT + DT


def test_palette_offset_moves_at_least_a_quarter():
    detector = SectionDetector(now=0.0, palette_interval=2.0, seed=5)
    previous = detector.palette_offset
    t = 0.0
    for _ in range(int(30.0 / DT)):
        t += DT
        detector.update(0.5, t)
        if detector.palette_changed:
            moved = (detector.palette_offset - previous) % 1.0
            assert 0.25 - 1e-9 <= moved <= 0.75 + 1e-9
            previous = detector.palette_offset


def test_seed_makes_the_detector_deterministic():
    a = SectionDetector(now=0.0, seed=7)
    b = SectionDetector(now=0.0, seed=7)
    t = 0.0
    for _ in range(int(40.0 / DT)):
        t += DT
        a.update(0.5, t)
        b.update(0.5, t)
    assert a.palette_offset == b.palette_offset


def test_reset_clears_the_state():
    detector = SectionDetector(now=0.0, seed=1)
    feed(detector, 1.0, 3.0, 0.0)
    detector.reset(100.0)
    assert detector.section == "quiet"
    assert detector.level == 0.0
    assert detector.time_in_section(100.0) == 0.0


def test_sections_list():
    assert SECTIONS == ["quiet", "soft", "loud"]
