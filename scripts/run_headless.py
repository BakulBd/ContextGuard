"""Quick local sanity check: runs the full pipeline against a real
camera and shows the annotated feed in a plain OpenCV window.

This is the fastest way to confirm detection, tracking, zones, and
risk overlay actually work on your machine (project-plan Week 1-6
checkpoint) before touching the Streamlit dashboard at all.

Usage:
    python scripts/run_headless.py
    python scripts/run_headless.py --camera 1
    (press 'q' in the window to quit)
"""

from __future__ import annotations

import argparse

import cv2

from contextguard.config import load_config
from contextguard.pipeline import ContextGuardPipeline


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--camera", default=None, help="override config.yaml's camera_source (e.g. 0, 1)")
    args = parser.parse_args()

    config = load_config()
    if args.camera is not None:
        config.camera_source = args.camera

    pipeline = ContextGuardPipeline(config)
    pipeline.start()
    print(f"Monitoring camera '{config.camera_source}' ({len(pipeline.zones.zones)} zone(s) configured).")
    print("Press 'q' in the video window to quit.")

    try:
        while True:
            result = pipeline.step()
            if result is None:
                print("No frame read -- camera may be busy or disconnected. Retrying...")
                continue

            cv2.putText(
                result.frame,
                f"FPS {result.fps:.1f}  latency {result.avg_latency_ms:.0f}ms  "
                f"CPU {result.cpu_percent:.0f}%  RAM {result.mem_mb:.0f}MB",
                (10, result.frame.shape[0] - 12),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )
            cv2.imshow("ContextGuard", result.frame)

            for event in result.new_events:
                print(f"[EVENT] {event.narrative}")

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        pipeline.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
