import cv2
import numpy as np

from ai.vision.train_videomae_classifier import read_video_frames


def test_read_video_frames_accepts_prepared_frame_directory(tmp_path):
    for index, value in enumerate((20, 100, 220)):
        cv2.imwrite(str(tmp_path / f"frame_{index:03d}.jpg"), np.full((8, 8, 3), value, np.uint8))

    frames = read_video_frames(tmp_path, 3)

    assert len(frames) == 3
    assert all(frame.shape == (8, 8, 3) for frame in frames)
    assert all(frame.any() for frame in frames)
