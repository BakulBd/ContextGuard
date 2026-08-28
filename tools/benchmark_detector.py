"""Benchmark the person detector (and optionally the tracker) on THIS
machine.

Published FPS numbers -- including the YOLO26n-vs-YOLOv8n figures this
project's default model choice is based on (Ultralytics' own benchmark,
arXiv 2605.24831: 38.9ms vs 80.4ms on CPU/ONNX, 40.9 vs 37.3 mAP) -- are
measured on specific hardware and export formats and shouldn't be taken
as gospel for a different laptop. This script measures latency, FPS,
and process memory against either live camera frames or synthetic ones
(if no camera is available), so the model-selection decision is based
on a number actually produced on the deployment machine.

Usage:
    python tools/benchmark_detector.py --source 0 --frames 150
    python tools/benchmark_detector.py --source synthetic --frames 150
    python tools/benchmark_detector.py --source 0 --with-tracking
    python tools/benchmark_detector.py --compare        # yolo26n vs yolov8n, back to back
"""

from __future__ import annotations

import argparse
import dataclasses
import statistics
import time

import numpy as np

from contextguard.camera import CameraSource, probe
from contextguard.perf import PerfMonitor
from contextguard.tracking import PersonDetector, PersonTracker

DEFAULT_MODEL = "yolo26n.pt"
COMPARE_MODELS = ["yolo26n.pt", "yolov8n.pt"]


@dataclasses.dataclass
class BenchmarkResult:
    model_name: str
    source: str
    frames: int
    load_seconds: float
    mean_fps: float
    mean_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    mem_mb: float
    mean_detections: float


def _frame_source(source: str, width: int, height: int, count: int):
    if source == "synthetic":
        rng = np.random.default_rng(7)
        for _ in range(count):
            yield rng.integers(0, 255, size=(height, width, 3), dtype=np.uint8)
        return

    cam = CameraSource(source, width, height)
    cam.open()
    try:
        produced = 0
        misses = 0
        while produced < count:
            frame = cam.read()
            if frame is not None:
                produced += 1
                yield frame
            else:
                misses += 1
                if misses > count * 5:
                    raise RuntimeError("camera stopped returning frames mid-benchmark")
    finally:
        cam.release()


def run(source: str, frames: int, model_name: str, with_tracking: bool, width: int, height: int) -> BenchmarkResult:
    print(f"Loading {model_name} ({'detect+track' if with_tracking else 'detect only'}) ...")
    t_load0 = time.perf_counter()
    engine = PersonTracker(model_name=model_name) if with_tracking else PersonDetector(model_name=model_name)
    load_seconds = time.perf_counter() - t_load0
    print(f"Model load time: {load_seconds:.2f}s")

    # A first inference call pays a one-off graph/allocator warmup cost
    # that isn't representative of steady state; discard it from the timing.
    warm_frame = np.zeros((height, width, 3), dtype=np.uint8)
    (engine.update if with_tracking else engine.detect)(warm_frame)

    perf = PerfMonitor(window=frames)
    latencies_ms: list[float] = []
    det_counts: list[int] = []

    for frame in _frame_source(source, width, height, frames):
        t0 = time.perf_counter()
        results = engine.update(frame) if with_tracking else engine.detect(frame)
        dt = time.perf_counter() - t0
        latencies_ms.append(dt * 1000)
        det_counts.append(len(results))
        perf.tick(dt)

    sorted_ms = sorted(latencies_ms)
    p95 = sorted_ms[min(len(sorted_ms) - 1, int(len(sorted_ms) * 0.95))]

    result = BenchmarkResult(
        model_name=model_name,
        source=source,
        frames=len(latencies_ms),
        load_seconds=load_seconds,
        mean_fps=perf.fps,
        mean_latency_ms=statistics.mean(latencies_ms),
        p50_latency_ms=statistics.median(latencies_ms),
        p95_latency_ms=p95,
        mem_mb=perf.mem_mb(),
        mean_detections=statistics.mean(det_counts),
    )
    _print_result(result)
    return result


def _print_result(r: BenchmarkResult) -> None:
    print("\n--- Results (this machine only -- re-run on the deployment laptop) ---")
    print(f"Model:                 {r.model_name}")
    print(f"Source:                {r.source}")
    print(f"Frames processed:      {r.frames}")
    print(f"Mean FPS:              {r.mean_fps:.1f}")
    print(f"Mean latency:          {r.mean_latency_ms:.1f} ms")
    print(f"P50 / P95 latency:     {r.p50_latency_ms:.1f} / {r.p95_latency_ms:.1f} ms")
    print(f"Process RSS memory:    {r.mem_mb:.0f} MB")
    print(f"Mean detections/frame: {r.mean_detections:.2f}")


def _print_comparison(results: list[BenchmarkResult]) -> None:
    print("\n=== Comparison ===")
    header = f"{'model':<14}{'FPS':>8}{'mean ms':>10}{'P95 ms':>10}{'RSS MB':>10}"
    print(header)
    print("-" * len(header))
    for r in results:
        print(f"{r.model_name:<14}{r.mean_fps:>8.1f}{r.mean_latency_ms:>10.1f}{r.p95_latency_ms:>10.1f}{r.mem_mb:>10.0f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", default="0", help="camera index, or 'synthetic' for random frames")
    parser.add_argument("--frames", type=int, default=150)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument(
        "--with-tracking", action="store_true", help="measure detect+ByteTrack instead of detection alone"
    )
    parser.add_argument(
        "--compare", action="store_true", help=f"run {' and '.join(COMPARE_MODELS)} back to back and compare"
    )
    args = parser.parse_args()

    if args.source != "synthetic":
        if probe(args.source) is None:
            print(f"Could not open camera source '{args.source}' -- falling back to synthetic frames.")
            args.source = "synthetic"

    if args.compare:
        results = [
            run(args.source, args.frames, model, args.with_tracking, args.width, args.height)
            for model in COMPARE_MODELS
        ]
        _print_comparison(results)
    else:
        run(args.source, args.frames, args.model, args.with_tracking, args.width, args.height)


if __name__ == "__main__":
    main()
