"""Select impact-centred evidence frames from a video."""

from __future__ import annotations


def _uniform_indices(frame_count: int, target_count: int) -> list[int]:
    count = min(max(target_count, 1), frame_count)
    if count == 1:
        return [0]
    return [round(i * (frame_count - 1) / (count - 1)) for i in range(count)]


def select_impact_frame_indices(
    motion_scores: list[float], frame_count: int, target_count: int = 16
) -> list[int]:
    """Keep global context while concentrating frames around the motion peak."""
    if frame_count <= 0:
        return []
    count = min(max(target_count, 1), frame_count)
    uniform = _uniform_indices(frame_count, count)
    if not motion_scores or max(motion_scores) <= min(motion_scores):
        return uniform

    peak = min(max(range(len(motion_scores)), key=motion_scores.__getitem__) + 1, frame_count - 1)
    context = _uniform_indices(frame_count, min(4, count))
    local_count = max(0, count - len(context))
    start = max(0, peak - local_count // 2)
    stop = min(frame_count, start + local_count)
    start = max(0, stop - local_count)
    selected = sorted(set(context + list(range(start, stop))))
    for index in uniform:
        if len(selected) >= count:
            break
        if index not in selected:
            selected.append(index)
            selected.sort()
    while len(selected) > count:
        removable = [index for index in selected if index not in context and index != peak]
        selected.remove(removable[0] if removable else selected[-1])
    return selected


def grouped_impact_frame_indices(
    motion_scores: list[float], frame_count: int
) -> list[tuple[int, str]]:
    """Return the 4+4+4+4 evidence layout used by the verified 100-video run."""
    if frame_count <= 0:
        return []
    if frame_count < 16:
        roles = ("context", "pre_impact", "impact", "post_impact")
        return [
            (index, roles[min(order // 4, 3)])
            for order, index in enumerate(_uniform_indices(frame_count, 16))
        ]

    peak = (
        max(range(len(motion_scores)), key=motion_scores.__getitem__) + 1
        if motion_scores and max(motion_scores) > min(motion_scores)
        else frame_count // 2
    )
    peak = min(max(peak, 9), frame_count - 7)

    def four(start: int, stop: int) -> list[int]:
        if stop <= start:
            return [start] * 4
        return [round(start + index * (stop - start) / 3) for index in range(4)]

    before = _uniform_indices(peak - 1, 8)
    return [
        *((index, "context") for index in before[:4]),
        *((index, "pre_impact") for index in before[4:]),
        *((index, "impact") for index in range(peak - 1, peak + 3)),
        *((index, "post_impact") for index in four(peak + 3, frame_count - 1)),
    ]


def scan_video_motion_scores(video_path, frame_count: int, scan_count: int = 160) -> list[float]:
    """Run a low-cost optical-flow scan; zero scores trigger the uniform fallback."""
    import cv2

    scores = [0.0] * max(frame_count - 1, 0)
    if frame_count < 2:
        return scores
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return scores
    stride = max(frame_count // scan_count, 1)
    previous = None
    try:
        for index in range(0, frame_count, stride):
            cap.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = cap.read()
            if not ok:
                continue
            gray = cv2.cvtColor(cv2.resize(frame, (160, 90)), cv2.COLOR_BGR2GRAY)
            if previous is not None:
                flow = cv2.calcOpticalFlowFarneback(
                    previous, gray, None, 0.5, 2, 9, 2, 5, 1.1, 0
                )
                scores[min(index - 1, len(scores) - 1)] = float(
                    cv2.magnitude(flow[..., 0], flow[..., 1]).mean()
                )
            previous = gray
    finally:
        cap.release()
    return scores
