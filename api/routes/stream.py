"""Live video over HTTP: a single JPEG snapshot, and an MJPEG stream
(the same `multipart/x-mixed-replace` trick IP cameras have used for
decades -- plain `<img src="/stream.mjpg">` works in any browser, no
WebSocket/JS needed on the consuming side).
"""

from __future__ import annotations

import time
from collections.abc import Generator

import cv2
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, StreamingResponse

from ..security import require_api_key
from ..state import PipelineService, get_service

router = APIRouter(tags=["stream"], dependencies=[Depends(require_api_key)])


def _encode_jpeg(frame) -> bytes:
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        raise RuntimeError("JPEG encode failed")
    return buf.tobytes()


@router.get("/frame.jpg")
def frame_jpg() -> Response:
    frame = get_service().latest_frame()
    if frame is None:
        raise HTTPException(status_code=503, detail="no frame available yet")
    return Response(content=_encode_jpeg(frame), media_type="image/jpeg")


def _mjpeg_generator(service: PipelineService) -> Generator[bytes, None, None]:
    boundary = b"--frame"
    while True:
        frame = service.latest_frame()
        if frame is not None:
            jpg = _encode_jpeg(frame)
            yield (
                boundary
                + b"\r\nContent-Type: image/jpeg\r\nContent-Length: "
                + str(len(jpg)).encode()
                + b"\r\n\r\n"
                + jpg
                + b"\r\n"
            )
        time.sleep(0.05)  # ~20 fps cap on the stream regardless of capture rate -- plenty for a live view


@router.get("/stream.mjpg")
def stream_mjpg() -> StreamingResponse:
    return StreamingResponse(_mjpeg_generator(get_service()), media_type="multipart/x-mixed-replace; boundary=frame")
