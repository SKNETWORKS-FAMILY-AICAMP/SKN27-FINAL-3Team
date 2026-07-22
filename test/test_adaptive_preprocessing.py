import unittest

try:
    import numpy as np
    from ai.vision.adaptive_preprocessing import enhance_frame_adaptive, lighting_from_frame
except ModuleNotFoundError as exc:
    if exc.name == "cv2":
        raise unittest.SkipTest("optional OpenCV dependency is not installed") from exc
    raise


class AdaptivePreprocessingTest(unittest.TestCase):
    def test_dark_frame_is_classified_and_brightened(self):
        frame = np.full((40, 40, 3), 30, dtype=np.uint8)

        self.assertEqual(lighting_from_frame(frame)[0], "night")
        self.assertGreater(enhance_frame_adaptive(frame).mean(), frame.mean())

    def test_overexposed_frame_is_classified_and_darkened(self):
        frame = np.full((40, 40, 3), 245, dtype=np.uint8)

        self.assertEqual(lighting_from_frame(frame)[0], "overexposed")
        self.assertLess(enhance_frame_adaptive(frame).mean(), frame.mean())


if __name__ == "__main__":
    unittest.main()
