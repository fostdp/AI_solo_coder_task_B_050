"""
电化学噪声时频特征提取模块
基于小波包分解 (Wavelet Packet Decomposition, WPD)
提取电化学噪声信号的多尺度能量、熵、统计特征
"""

import numpy as np
import pywt
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field


@dataclass
class WaveletFeatures:
    total_energy: float = 0.0
    band_energies: Dict[str, float] = field(default_factory=dict)
    band_energy_ratios: Dict[str, float] = field(default_factory=dict)
    wavelet_entropy: float = 0.0
    statistical_features: Dict[str, float] = field(default_factory=dict)
    noise_resistance: float = 0.0
    pitting_index: float = 0.0


class WaveletPacketFeatureExtractor:
    def __init__(
        self,
        wavelet: str = "db4",
        max_level: int = 5,
        sampling_rate: int = 1000
    ):
        self.wavelet = wavelet
        self.max_level = max_level
        self.sampling_rate = sampling_rate

    def extract(
        self,
        voltage_signal: np.ndarray,
        current_signal: np.ndarray,
        area_cm2: float = 1.0
    ) -> WaveletFeatures:
        features = WaveletFeatures()

        voltage_signal = self._preprocess(voltage_signal)
        current_signal = self._preprocess(current_signal)

        features.statistical_features = self._extract_statistical(
            voltage_signal, current_signal
        )

        features.noise_resistance = self._calculate_noise_resistance(
            voltage_signal, current_signal, area_cm2
        )

        features.pitting_index = self._calculate_pitting_index(current_signal)

        volt_features = self._wavelet_packet_decompose(voltage_signal, "V")
        curr_features = self._wavelet_packet_decompose(current_signal, "I")

        features.band_energies = {**volt_features["energies"], **curr_features["energies"]}
        features.band_energy_ratios = {**volt_features["ratios"], **curr_features["ratios"]}
        features.total_energy = volt_features["total"] + curr_features["total"]
        features.wavelet_entropy = volt_features["entropy"] + curr_features["entropy"]

        return features

    def _preprocess(self, signal: np.ndarray) -> np.ndarray:
        signal = np.asarray(signal, dtype=np.float64)
        signal = signal[~np.isnan(signal)]
        if len(signal) < 32:
            signal = np.pad(signal, (0, 32 - len(signal)), mode="edge")
        detrended = signal - np.mean(signal)
        return detrended

    def _extract_statistical(
        self,
        voltage: np.ndarray,
        current: np.ndarray
    ) -> Dict[str, float]:
        features = {}

        features["V_mean"] = float(np.mean(voltage))
        features["V_std"] = float(np.std(voltage))
        features["V_rms"] = float(np.sqrt(np.mean(voltage ** 2)))
        features["V_skew"] = float(self._skewness(voltage))
        features["V_kurtosis"] = float(self._kurtosis(voltage))
        features["V_peak_to_peak"] = float(np.max(voltage) - np.min(voltage))
        features["V_cv"] = float(np.std(voltage) / (np.abs(np.mean(voltage)) + 1e-12))

        features["I_mean"] = float(np.mean(current))
        features["I_std"] = float(np.std(current))
        features["I_rms"] = float(np.sqrt(np.mean(current ** 2)))
        features["I_skew"] = float(self._skewness(current))
        features["I_kurtosis"] = float(self._kurtosis(current))
        features["I_peak_to_peak"] = float(np.max(current) - np.min(current))
        features["I_cv"] = float(np.std(current) / (np.abs(np.mean(current)) + 1e-12))

        if len(voltage) == len(current):
            features["cross_corr"] = float(
                np.correlate(voltage, current, mode="valid")[0] /
                (np.std(voltage) * np.std(current) * len(voltage) + 1e-12)
            )

        return features

    def _calculate_noise_resistance(
        self,
        voltage: np.ndarray,
        current: np.ndarray,
        area: float
    ) -> float:
        std_v = np.std(voltage)
        std_i = np.std(current)
        if std_i < 1e-15:
            return 1e12
        Rn = (std_v / std_i) * area
        return float(max(Rn, 0.1))

    def _calculate_pitting_index(self, current: np.ndarray) -> float:
        if len(current) < 3:
            return 0.0
        current_std = np.std(current)
        current_mean = np.abs(np.mean(current))
        if current_mean < 1e-15:
            return 0.0
        return float(current_std / current_mean)

    def _wavelet_packet_decompose(
        self,
        signal: np.ndarray,
        prefix: str
    ) -> Dict:
        wp = pywt.WaveletPacket(
            data=signal,
            wavelet=self.wavelet,
            mode="symmetric",
            maxlevel=self.max_level
        )

        leaf_nodes = [node.path for node in wp.get_level(self.max_level, "natural")]
        n_bands = len(leaf_nodes)

        energies = {}
        freq_bounds = []
        nyquist = self.sampling_rate / 2
        band_width = nyquist / n_bands

        for idx, path in enumerate(leaf_nodes):
            coeffs = wp[path].data
            energy = float(np.sum(coeffs ** 2))
            f_low = idx * band_width
            f_high = (idx + 1) * band_width
            key = f"{prefix}_{path}_{f_low:.0f}-{f_high:.0f}Hz"
            energies[key] = energy
            freq_bounds.append((f_low, f_high, energy))

        total_energy = sum(energies.values()) + 1e-12

        ratios = {}
        for key, energy in energies.items():
            ratios[key + "_ratio"] = energy / total_energy

        energy_dist = np.array(list(energies.values())) / total_energy
        energy_dist = energy_dist[energy_dist > 0]
        entropy = float(-np.sum(energy_dist * np.log2(energy_dist)))

        return {
            "energies": energies,
            "ratios": ratios,
            "total": float(total_energy),
            "entropy": entropy,
            "freq_bands": freq_bounds
        }

    @staticmethod
    def _skewness(x: np.ndarray) -> float:
        n = len(x)
        if n < 3:
            return 0.0
        mean = np.mean(x)
        std = np.std(x)
        if std < 1e-15:
            return 0.0
        return (n / ((n - 1) * (n - 2))) * np.sum(((x - mean) / std) ** 3)

    @staticmethod
    def _kurtosis(x: np.ndarray) -> float:
        n = len(x)
        if n < 4:
            return 0.0
        mean = np.mean(x)
        std = np.std(x)
        if std < 1e-15:
            return 0.0
        s = np.sum(((x - mean) / std) ** 4)
        return ((n * (n + 1)) / ((n - 1) * (n - 2) * (n - 3))) * s - \
            (3 * (n - 1) ** 2) / ((n - 2) * (n - 3))


def features_to_feature_vector(features: WaveletFeatures) -> Tuple[np.ndarray, List[str]]:
    vector = []
    names = []

    for k, v in features.statistical_features.items():
        vector.append(v)
        names.append(k)

    for k, v in features.band_energy_ratios.items():
        vector.append(v)
        names.append(k)

    vector.append(features.wavelet_entropy)
    names.append("wavelet_entropy")

    vector.append(np.log10(features.noise_resistance + 1e-6))
    names.append("log_noise_resistance")

    vector.append(features.pitting_index)
    names.append("pitting_index")

    return np.array(vector, dtype=np.float64), names
