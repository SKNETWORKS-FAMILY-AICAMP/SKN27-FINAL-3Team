"""Adaptive frame enhancement and motion-aware sampling for vision experiments."""

from pathlib import Path

import cv2
import numpy as np


def _gamma(frame, value):
    table = np.array([((i / 255.0) ** value) * 255 for i in range(256)], dtype=np.uint8)
    return cv2.LUT(frame, table)


def _clahe(frame, clip_limit):
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    lightness, a, b = cv2.split(lab)
    lightness = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(8, 8)).apply(lightness)
    return cv2.cvtColor(cv2.merge((lightness, a, b)), cv2.COLOR_LAB2BGR)


def _sharpen(frame, amount):
    blurred = cv2.GaussianBlur(frame, (0, 0), 3)
    return cv2.addWeighted(frame, 1.0 + amount, blurred, -amount, 0)


def lighting_from_frame(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    mean = float(gray.mean())
    high = float(np.percentile(gray, 95))
    if mean < 45:
        return "night", mean
    if mean < 85:
        return "low_light", mean
    if mean > 175 and high >= 245:
        return "overexposed", mean
    return "day", mean


def enhance_frame_adaptive(frame):
    mode, mean = lighting_from_frame(frame)
    if mode in {"night", "low_light"}:
        denoised = cv2.bilateralFilter(frame, 5, 30, 30)
        gamma = 0.60 if mode == "night" else 0.78
        return _sharpen(_clahe(_gamma(denoised, gamma), 2.0), 0.15)
    if mode == "overexposed":
        return _sharpen(_gamma(frame, 1.30), 0.12)
    return _sharpen(_clahe(frame, 1.5), 0.20)


def select_collision_aware_frames(paths, count):
    paths = list(paths)
    if count < 1:
        raise ValueError("frame sample count must be positive")
    if len(paths) <= count:
        return paths

    grays = []
    for path in paths:
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if image is None:
            grays.append(None)
        else:
            grays.append(cv2.resize(image, (160, 90), interpolation=cv2.INTER_AREA))

    scores = []
    for index in range(1, len(grays)):
        if grays[index - 1] is None or grays[index] is None:
            score = -1.0
        else:
            score = float(cv2.absdiff(grays[index - 1], grays[index]).mean())
        scores.append((score, index))

    chosen = {0, len(paths) - 1}
    minimum_gap = max(1, len(paths) // (count * 2))
    for _, index in sorted(scores, reverse=True):
        if len(chosen) >= count:
            break
        if all(abs(index - current) >= minimum_gap for current in chosen):
            chosen.add(index)

    if len(chosen) < count:
        uniform = [round(i * (len(paths) - 1) / (count - 1)) for i in range(count)]
        chosen.update(uniform)

    selected = sorted(chosen)[:count]
    return [paths[index] for index in selected]


def _self_check():
    dark = np.full((40, 40, 3), 30, dtype=np.uint8)
    bright = np.full((40, 40, 3), 245, dtype=np.uint8)
    assert enhance_frame_adaptive(dark).mean() > dark.mean()
    assert enhance_frame_adaptive(bright).mean() < bright.mean()
    assert lighting_from_frame(dark)[0] == "night"
    assert lighting_from_frame(bright)[0] == "overexposed"


if __name__ == "__main__":
    _self_check()
    print("adaptive_preprocessing: OK")
