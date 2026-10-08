"""Triangular filter banks on the Mel frequency scale."""

import numpy as np


def hertz_to_mel(freq):
    """Convert a scalar or array of frequencies from hertz to Mel."""

    return 3340.0 * (np.log(1 + (freq / 250.0)) / np.log(9))


def mel_to_hertz(mel):
    """Convert a scalar or array of Mel frequencies to hertz."""

    return 250.0 * (9 ** (mel / 3340.0)) - 250.0


def melfrequencies_mel_filterbank(num_bands, freq_min, freq_max, num_fft_bands):
    """Return (centers, lower_edges, upper_edges), all in Mel."""

    mel_max = hertz_to_mel(freq_max)
    mel_min = hertz_to_mel(freq_min)

    delta_mel = abs(mel_max - mel_min) / (num_bands + 1.0)

    frequencies_mel = mel_min + delta_mel * np.arange(0, num_bands + 2)

    lower_edges_mel = frequencies_mel[:-2]
    upper_edges_mel = frequencies_mel[2:]
    center_frequencies_mel = frequencies_mel[1:-1]

    return center_frequencies_mel, lower_edges_mel, upper_edges_mel


def compute_melmat(
    num_mel_bands=12,
    freq_min=64,
    freq_max=8000,
    num_fft_bands=513,
    sample_rate=16000,
):
    """Return (band-by-FFT matrix, band centers in Hz, FFT frequencies in Hz)."""

    (
        center_frequencies_mel,
        lower_edges_mel,
        upper_edges_mel,
    ) = melfrequencies_mel_filterbank(num_mel_bands, freq_min, freq_max, num_fft_bands)

    center_frequencies_hz = mel_to_hertz(center_frequencies_mel)
    lower_edges_hz = mel_to_hertz(lower_edges_mel)
    upper_edges_hz = mel_to_hertz(upper_edges_mel)

    freqs = np.linspace(0.0, sample_rate / 2.0, num_fft_bands)

    melmat = np.zeros((num_mel_bands, num_fft_bands))

    for imelband, (center, lower, upper) in enumerate(
        zip(center_frequencies_hz, lower_edges_hz, upper_edges_hz)
    ):
        left_slope = (freqs >= lower) & (freqs <= center)
        melmat[imelband, left_slope] = (freqs[left_slope] - lower) / (center - lower)

        right_slope = (freqs >= center) & (freqs <= upper)
        melmat[imelband, right_slope] = (upper - freqs[right_slope]) / (upper - center)

    return (melmat, center_frequencies_hz, freqs)


def compute_melmat_from_range(
    lower_edges_hz, upper_edges_hz, num_fft_bands=513, sample_rate=16000
):
    """Build the same matrix and frequency tuple from explicit band edges in Hz."""

    melmat = np.zeros((len(lower_edges_hz), num_fft_bands))

    freqs = np.linspace(0.0, sample_rate / 2.0, num_fft_bands)

    center_frequencies_hz = np.mean([lower_edges_hz, upper_edges_hz], axis=0)

    for imelband, (lower, center, upper) in enumerate(
        zip(lower_edges_hz, center_frequencies_hz, upper_edges_hz)
    ):
        left_slope = (freqs >= lower) & (freqs <= center)
        melmat[imelband, left_slope] = (freqs[left_slope] - lower) / (center - lower)

        right_slope = (freqs >= center) & (freqs <= upper)
        melmat[imelband, right_slope] = (upper - freqs[right_slope]) / (upper - center)

    return (melmat, center_frequencies_hz, freqs)
