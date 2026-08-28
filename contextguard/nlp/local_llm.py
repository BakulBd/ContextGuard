"""Small local-model narration backend -- the second point of comparison
in the template vs. small-local-model vs. LLM study the project
proposal calls for (the third point, an external LLM, is deliberately
left as an evaluation-harness-only concern; see the proposal's privacy
argument for why it never belongs in the deployed path).

Optional on purpose: importing this module without ``transformers``
installed raises a clear, actionable error instead of an ImportError
stack trace -- install with ``pip install -e ".[localllm]"``.

Model choice: SmolLM2-360M-Instruct (Apache 2.0, HuggingFace's own
small-model family, purpose-built for on-device/edge instruction
following) over a larger "best CPU model" pick -- this runs inside the
same process as the detection pipeline, generating one short sentence
per *event* (not per frame), so latency and memory footprint matter
more here than raw capability. Swap ``local_llm_model`` in config.yaml
for something larger (e.g. Qwen2.5-0.5B-Instruct) if quality matters
more than footprint for your deployment.

Every output still passes through ``check_grounding`` from
generate.py -- a small instruct model narrating structured data is
exactly the failure mode that checker exists for.
"""

from __future__ import annotations

from ..events import Event
from .generate import format_clock, format_duration

DEFAULT_MODEL = "HuggingFaceTB/SmolLM2-360M-Instruct"

_SYSTEM_PROMPT = (
    "You write single, factual sentences describing security camera events for a monitoring log. "
    "Rules: use ONLY the facts given below. Never invent a name, location, time, or duration. "
    "Never use words like criminal, intruder, suspect, thief, or dangerous -- describe only what was "
    "observed, not a judgment about the person. Output exactly one sentence, nothing else."
)


def build_prompt(event: Event) -> list[dict[str, str]]:
    """Pure and unit-testable without loading any model: turns an Event
    into the chat-format messages passed to the tokenizer's chat
    template. Kept separate from ``LocalLLMNarrator`` so prompt
    construction can be tested without a multi-hundred-MB model.
    """
    identity_phrase = "unidentified" if event.identity in ("unknown", "", None) else event.identity
    facts = [
        f"time: {format_clock(event.timestamp)}",
        f"identity: {identity_phrase}",
        f"zone: {event.zone or 'unspecified area'}",
    ]
    if "loitering" in event.behavior:
        facts.append(f"duration in zone: {format_duration(event.duration_seconds)}")
    if event.behavior and event.behavior != ["normal"]:
        facts.append(f"observed behavior tags: {', '.join(t for t in event.behavior if t != 'normal')}")
    facts.append(f"risk level: {event.risk_level}")

    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "Event facts:\n" + "\n".join(f"- {f}" for f in facts)},
    ]


class LocalLLMNarrator:
    """Generator-compatible with ``EventNarrator`` (same ``generate(event)
    -> str`` signature), so it's a drop-in swap wherever the template
    narrator is used -- pipeline.py, the dashboard, and
    tools/compare_narrators.py all take either one.

    The model loads lazily on first ``generate()`` call, not at
    construction, so simply importing this module (or selecting it in
    config without ever calling it) never pays the load cost.
    """

    def __init__(self, model_name: str = DEFAULT_MODEL, max_new_tokens: int = 60, device: str = "cpu"):
        self.model_name = model_name
        self.max_new_tokens = max_new_tokens
        self.device = device
        self._pipe = None

    def _ensure_loaded(self):
        if self._pipe is not None:
            return self._pipe
        try:
            from transformers import pipeline
        except ImportError as exc:
            raise ImportError(
                "LocalLLMNarrator needs the 'transformers' package. "
                'Install with: pip install -e ".[localllm]"'
            ) from exc

        self._pipe = pipeline(
            "text-generation",
            model=self.model_name,
            device=self.device,
            torch_dtype="auto",
        )
        return self._pipe

    def generate(self, event: Event) -> str:
        pipe = self._ensure_loaded()
        messages = build_prompt(event)
        output = pipe(
            messages,
            max_new_tokens=self.max_new_tokens,
            do_sample=False,  # deterministic -- this is a monitoring log, not a creative-writing task
            temperature=None,
            top_p=None,
        )
        generated = output[0]["generated_text"]
        # `generated_text` for a chat pipeline is the full message list
        # (including the input); the model's reply is the last assistant turn.
        reply = generated[-1]["content"] if isinstance(generated, list) else str(generated)
        return reply.strip().split("\n")[0].strip()
