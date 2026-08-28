"""ContextGuard dashboard.

Deliberately thin: every real decision (detection, tracking, zones,
risk, narration, alerting) happens in the `contextguard` package.
This file is presentation only -- live feed, zone editor, event
panel, timeline, and the natural-language query box.

Run with:  streamlit run dashboard/app.py
"""

from __future__ import annotations

import hmac
import os
import sys
import time
from pathlib import Path

import cv2
import pandas as pd
import streamlit as st
from PIL import Image
from streamlit_drawable_canvas import st_canvas

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contextguard.camera import CameraSource
from contextguard.config import load_config, resolve_path
from contextguard.events import EventStore
from contextguard.geometry import normalize
from contextguard.logging_setup import get_logger
from contextguard.nlp.query import NLQueryEngine
from contextguard.pipeline import ContextGuardPipeline
from contextguard.zones import Zone, ZoneManager

log = get_logger("dashboard")

st.set_page_config(page_title="ContextGuard", layout="wide", page_icon="🛡️")


def _check_password() -> bool:
    """Gate the dashboard behind a password when one is configured.

    This page shows a live camera feed and a security event log --
    treat it like the sensitive surface it is the moment it's reachable
    from anywhere beyond localhost. No password set means "trusted to
    localhost only" (the default `streamlit run` binding); see the
    README's Production Deployment section before exposing this on a
    LAN or the internet.
    """
    required = os.environ.get("CONTEXTGUARD_DASHBOARD_PASSWORD")
    if not required:
        return True
    if st.session_state.get("authenticated"):
        return True

    st.title("🛡️ ContextGuard")
    st.caption("Authentication required.")
    pw = st.text_input("Dashboard password", type="password", key="pw_input")
    if st.button("Sign in"):
        if hmac.compare_digest(pw, required):
            st.session_state.authenticated = True
            log.info("Dashboard sign-in succeeded.")
            st.rerun()
        else:
            log.warning("Dashboard sign-in failed (wrong password).")
            st.error("Incorrect password.")
    return False


if not _check_password():
    st.stop()

# -- session state ------------------------------------------------------------

if "config" not in st.session_state:
    st.session_state.config = load_config()
if "pipeline" not in st.session_state:
    st.session_state.pipeline = None
if "running" not in st.session_state:
    st.session_state.running = False
if "zone_snapshot" not in st.session_state:
    st.session_state.zone_snapshot = None

config = st.session_state.config


def get_store() -> EventStore:
    if st.session_state.pipeline is not None:
        return st.session_state.pipeline.store
    return EventStore(resolve_path(config.db_path))


def grab_snapshot():
    """Best-effort single-frame grab for the zone editor -- reuses the
    live pipeline's camera if monitoring is already running, otherwise
    opens (and immediately releases) a throwaway capture handle.
    """
    if st.session_state.running and st.session_state.pipeline is not None and st.session_state.pipeline.camera:
        return st.session_state.pipeline.camera.read()
    cam = CameraSource(config.camera_source, config.capture_width, config.capture_height)
    try:
        cam.open()
        cam.read()  # first frame off a freshly opened device is sometimes stale
        return cam.read()
    except Exception:
        return None
    finally:
        cam.release()


def rect_object_to_polygon(obj: dict) -> list[tuple[float, float]]:
    left, top = obj["left"], obj["top"]
    width = obj["width"] * obj.get("scaleX", 1)
    height = obj["height"] * obj.get("scaleY", 1)
    return [(left, top), (left + width, top), (left + width, top + height), (left, top + height)]


# -- sidebar --------------------------------------------------------------

with st.sidebar:
    st.title("🛡️ ContextGuard")
    st.caption("Laptop-webcam context-aware security monitoring")

    config.camera_source = st.text_input(
        "Camera source", value=config.camera_source, help="Webcam index (0, 1, ...) or an rtsp:// URL"
    )
    config.conf_threshold = st.slider("Detection confidence", 0.10, 0.90, config.conf_threshold, 0.05)
    config.risk_mode = st.selectbox(
        "Risk engine",
        ["rule", "weighted", "ml"],
        index=["rule", "weighted", "ml"].index(config.risk_mode),
        help="A: hand-picked rule · B: weights derived from a trained model · C: logistic regression directly. "
        "B/C fall back to A until tools/train_risk_model.py has produced them.",
    )
    st.caption("Identity mode: **anonymous** (privacy-preserving default). Enrolled-person recognition is a "
               "stretch feature not implemented in this build — see contextguard/identity.py.")

    st.caption("Changes to camera/confidence/risk-engine apply the next time you press Start.")
    col_start, col_stop = st.columns(2)
    if col_start.button("▶ Start", use_container_width=True, disabled=st.session_state.running):
        if st.session_state.pipeline is not None:
            st.session_state.pipeline.stop()
        st.session_state.pipeline = ContextGuardPipeline(config)
        st.session_state.pipeline.start()
        st.session_state.running = True
        st.rerun()
    if col_stop.button("⏸ Stop", use_container_width=True, disabled=not st.session_state.running):
        st.session_state.running = False
        if st.session_state.pipeline is not None:
            st.session_state.pipeline.stop()
        st.rerun()

    st.divider()
    with st.expander("Zones", expanded=not st.session_state.running):
        zm = ZoneManager.load(resolve_path(config.zones_path))
        if not zm.zones:
            st.caption("No zones configured yet — the risk engine still runs, but every event will show zone: none.")
        for zone in list(zm.zones):
            c1, c2 = st.columns([3, 1])
            c1.markdown(f"**{zone.name}** · _{zone.kind}_")
            if c2.button("🗑", key=f"del_{zone.name}"):
                zm.remove(zone.name)
                zm.save()
                if st.session_state.pipeline is not None:
                    st.session_state.pipeline.reload_zones()
                st.rerun()

        st.divider()
        st.write("**Add a zone**")
        if st.button("📷 Capture frame"):
            frame = grab_snapshot()
            if frame is None:
                st.error("Could not read a frame — check the camera source above.")
            else:
                st.session_state.zone_snapshot = frame
                st.rerun()

        if st.session_state.zone_snapshot is not None:
            rgb = cv2.cvtColor(st.session_state.zone_snapshot, cv2.COLOR_BGR2RGB)
            h, w = rgb.shape[:2]
            st.caption("Drag a rectangle over the area to protect, then name it below.")
            canvas_result = st_canvas(
                fill_color="rgba(224, 129, 88, 0.25)",
                stroke_width=2,
                stroke_color="#e07a4c",
                background_image=Image.fromarray(rgb),
                update_streamlit=True,
                height=h,
                width=w,
                drawing_mode="rect",
                key="zone_canvas",
            )
            zone_name = st.text_input("Zone name", value="restricted-area", key="zone_name_input")
            zone_kind = st.selectbox("Zone kind", ["restricted", "normal"], key="zone_kind_input")
            save_col, cancel_col = st.columns(2)
            if save_col.button("Save zone", use_container_width=True):
                objects = (canvas_result.json_data or {}).get("objects", []) if canvas_result else []
                rects = [o for o in objects if o.get("type") == "rect"]
                if not rects or not zone_name.strip():
                    st.error("Draw a rectangle and give it a name first.")
                else:
                    polygon = normalize(rect_object_to_polygon(rects[-1]), w, h)
                    zm.add(Zone(name=zone_name.strip(), kind=zone_kind, polygon=polygon))
                    zm.save()
                    if st.session_state.pipeline is not None:
                        st.session_state.pipeline.reload_zones()
                    st.session_state.zone_snapshot = None
                    st.success(f"Saved zone '{zone_name}'.")
                    st.rerun()
            if cancel_col.button("Cancel", use_container_width=True):
                st.session_state.zone_snapshot = None
                st.rerun()

    with st.expander("Privacy & retention"):
        st.caption(
            f"Structured events only — no continuous video retained by default. "
            f"Event retention: {config.retention_days} days. "
            f"Alerts fire locally only (on-screen + desktop notification), min level: {config.alert_risk_level}."
        )

# -- main area --------------------------------------------------------------

left, right = st.columns([2, 1])

with left:
    st.subheader("Live feed")
    frame_slot = st.empty()
    m1, m2, m3, m4 = st.columns(4)
    fps_metric, latency_metric, cpu_metric, mem_metric = m1.empty(), m2.empty(), m3.empty(), m4.empty()

with right:
    tab_events, tab_timeline, tab_ask = st.tabs(["Events", "Timeline", "Ask ContextGuard"])

    with tab_events:
        store = get_store()
        events = store.recent(minutes=60, limit=100)
        if not events:
            st.info("No events recorded in the last hour.")
        else:
            df = pd.DataFrame(
                [
                    {
                        "time": e.timestamp,
                        "identity": e.identity,
                        "zone": e.zone or "-",
                        "risk": int(e.risk_score),
                        "level": e.risk_level,
                        "behavior": ", ".join(e.behavior),
                    }
                    for e in events
                ]
            )
            st.dataframe(df, use_container_width=True, height=240)

            options = {f"#{e.event_id} · {e.timestamp} · {e.zone or '-'} · risk {int(e.risk_score)}": e for e in events}
            pick = st.selectbox("Incident detail", list(options.keys()))
            if pick:
                ev = options[pick]
                st.markdown(f"_{ev.narrative}_")
                if ev.risk_breakdown:
                    st.caption("Risk breakdown")
                    st.bar_chart(pd.Series(ev.risk_breakdown, name="points"))

    with tab_timeline:
        store = get_store()
        events = store.query(limit=5000, order="asc")
        if not events:
            st.info("No events yet.")
        else:
            by_hour = pd.Series([e.timestamp[:13] for e in events]).value_counts().sort_index()
            st.caption("Events per hour")
            st.bar_chart(by_hour)
            zone_counts = store.zone_incident_counts()
            if zone_counts:
                st.caption("Incidents by zone")
                st.bar_chart(pd.Series(zone_counts))

    with tab_ask:
        st.caption('Try: "What happened in the last 30 minutes?" · "Were there any high-risk events?" '
                    '· "Which zone had the most incidents?"')
        question = st.text_input("Ask about recorded events", key="nl_question")
        if question:
            zone_names = [z.name for z in ZoneManager.load(resolve_path(config.zones_path)).zones]
            engine = NLQueryEngine(zone_names=zone_names, risk_thresholds=config.risk_thresholds)
            result = engine.answer(question, get_store())
            st.markdown(f"**{result.text}**")
            with st.expander("Parsed query & retrieved rows (audit trail)"):
                st.json({"intent": result.parsed.intent, "filters": result.parsed.filters})
                if result.rows:
                    st.dataframe(
                        pd.DataFrame(
                            [{"time": e.timestamp, "zone": e.zone, "risk": e.risk_score, "level": e.risk_level} for e in result.rows]
                        ),
                        use_container_width=True,
                    )

# -- live loop ------------------------------------------------------------
# Streamlit has no persistent background loop; the standard pattern for a
# live camera feed is to process one frame per script run and immediately
# trigger a rerun. A widget interaction (e.g. the Stop button) preempts an
# in-flight rerun, so the UI stays responsive.

if st.session_state.running and st.session_state.pipeline is not None:
    result = st.session_state.pipeline.step()
    if result is not None:
        frame_slot.image(result.frame, channels="BGR", use_container_width=True)
        fps_metric.metric("FPS", f"{result.fps:.1f}")
        latency_metric.metric("Latency", f"{result.avg_latency_ms:.0f} ms")
        cpu_metric.metric("CPU", f"{result.cpu_percent:.0f}%")
        mem_metric.metric("RAM", f"{result.mem_mb:.0f} MB")
    else:
        frame_slot.warning("No frame read from the camera — check the source and permissions, then Stop/Start.")
    time.sleep(0.01)
    st.rerun()
else:
    frame_slot.info("Press ▶ Start in the sidebar to begin monitoring.")
