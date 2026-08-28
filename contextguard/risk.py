"""Risk engine: three approaches, sharing one feature set and one
explainable output shape, so they can be swapped and compared fairly.

  Approach A (RuleRiskEngine, default weights)
      Hand-picked point values -- the naive starting point, and the
      thing the project explicitly should NOT stop at.

  Approach B (RuleRiskEngine, derived weights)
      Same additive-points formula, but the weights are *derived* from
      Approach C's fitted coefficients via ``derive_weights_from_model``
      rather than guessed -- see the project proposal's justification
      for why this satisfies "don't arbitrarily assign weights" while
      keeping the score human-readable.

  Approach C (LogisticRiskEngine)
      A logistic regression trained on labeled (features -> should
      this have alerted?) rows. Needs real labeled data to be
      meaningful; ``tools/train_risk_model.py`` trains it and
      ``derive_weights_from_model`` below turns it into Approach B.

Until that labeled dataset exists (Week 4-6 of the project plan),
Approach A's hand-picked defaults are what the live pipeline uses --
and the code says so out loud rather than pretending otherwise.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Callable, Optional

from .config import RiskThresholds

# Order matters: this is the feature vector layout used by both the
# rule engines' breakdown dict and the ML model's training matrix.
FEATURE_ORDER = [
    "restricted_zone",
    "after_hours",
    "loitering",
    "unknown_identity",
    "repeat_visit",
    "abnormal_transition",
]

FEATURE_LABELS = {
    "restricted_zone": "restricted-zone entry",
    "after_hours": "unusual hour",
    "loitering": "prolonged presence",
    "unknown_identity": "unknown identity",
    "repeat_visit": "repeated entry",
    "abnormal_transition": "abnormal zone transition",
}

DEFAULT_WEIGHTS = {
    "restricted_zone": 30,
    "after_hours": 20,
    "loitering": 15,
    "unknown_identity": 12,
    "repeat_visit": 10,
    "abnormal_transition": 8,
}


@dataclasses.dataclass
class RiskFeatures:
    identity_known: bool
    zone_kind: Optional[str]  # "restricted" | "normal" | None
    after_hours: bool
    dwell_seconds: float
    is_loitering: bool
    repeat_visit_count: int
    abnormal_transition: bool


@dataclasses.dataclass
class RiskResult:
    score: float
    level: str
    breakdown: dict[str, float]  # descriptive label -> points contributed


def featurize(features: RiskFeatures, repeat_visit_threshold: int = 2) -> list[float]:
    """RiskFeatures -> fixed-order binary vector, for the ML model."""
    return [
        1.0 if features.zone_kind == "restricted" else 0.0,
        1.0 if features.after_hours else 0.0,
        1.0 if features.is_loitering else 0.0,
        0.0 if features.identity_known else 1.0,
        1.0 if features.repeat_visit_count >= repeat_visit_threshold else 0.0,
        1.0 if features.abnormal_transition else 0.0,
    ]


def _active_flags(features: RiskFeatures, repeat_visit_threshold: int) -> dict[str, bool]:
    return dict(
        zip(
            FEATURE_ORDER,
            [
                features.zone_kind == "restricted",
                features.after_hours,
                features.is_loitering,
                not features.identity_known,
                features.repeat_visit_count >= repeat_visit_threshold,
                features.abnormal_transition,
            ],
        )
    )


# ---------------------------------------------------------------------------
# Baselines -- the naive systems the proposed approach has to beat.
# Each is (bool) "would this baseline fire an alert for this observation?"
# ---------------------------------------------------------------------------

def baseline_1_person_detected(_: RiskFeatures) -> bool:
    return True


def baseline_2_unknown_person(features: RiskFeatures) -> bool:
    return not features.identity_known


def baseline_3_unknown_restricted(features: RiskFeatures) -> bool:
    return not features.identity_known and features.zone_kind == "restricted"


BASELINES: dict[str, Callable[[RiskFeatures], bool]] = {
    "baseline_1_person_detected": baseline_1_person_detected,
    "baseline_2_unknown_person": baseline_2_unknown_person,
    "baseline_3_unknown_restricted": baseline_3_unknown_restricted,
}


# ---------------------------------------------------------------------------
# Approaches A / B: additive point rules over the same weight shape.
# ---------------------------------------------------------------------------

class RuleRiskEngine:
    """Approach A with ``DEFAULT_WEIGHTS`` (hand-picked); Approach B when
    constructed with weights loaded from ``derive_weights_from_model``.
    Identical scoring logic either way -- only the weights differ.
    """

    def __init__(
        self,
        weights: Optional[dict[str, float]] = None,
        thresholds: Optional[RiskThresholds] = None,
        repeat_visit_threshold: int = 2,
    ):
        self.weights = weights or dict(DEFAULT_WEIGHTS)
        self.thresholds = thresholds or RiskThresholds()
        self.repeat_visit_threshold = repeat_visit_threshold

    def score(self, features: RiskFeatures) -> RiskResult:
        active = _active_flags(features, self.repeat_visit_threshold)
        breakdown = {
            FEATURE_LABELS[key]: self.weights.get(key, 0)
            for key, is_active in active.items()
            if is_active and self.weights.get(key, 0) > 0
        }
        score = min(100.0, sum(breakdown.values()))
        return RiskResult(score=score, level=self.thresholds.level_for(score), breakdown=breakdown)


def derive_weights_from_model(
    coefficients: list[float],
    feature_order: list[str] = FEATURE_ORDER,
    points_budget: int = 100,
) -> dict[str, int]:
    """Turn fitted logistic-regression coefficients into an interpretable
    points rule (Approach B), instead of hand-picking numbers.

    Negative coefficients (a feature that *reduces* predicted risk) have
    no sensible representation in an additive-points rule, so they're
    floored at zero -- documented, not hidden, since it's a real
    simplification relative to what the classifier actually learned.
    """
    positive = {name: max(c, 0.0) for name, c in zip(feature_order, coefficients)}
    total = sum(positive.values())
    if total <= 0:
        raise ValueError("no positive coefficients to derive weights from -- check the trained model")
    return {name: round(v / total * points_budget) for name, v in positive.items()}


def save_weights(weights: dict[str, int], path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(weights, indent=2))


def load_weights(path: str | Path) -> dict[str, int]:
    return json.loads(Path(path).read_text())


# ---------------------------------------------------------------------------
# Approach C: logistic regression classifier.
# ---------------------------------------------------------------------------

class LogisticRiskEngine:
    """Wraps a scikit-learn Pipeline (StandardScaler + LogisticRegression)
    trained by tools/train_risk_model.py. Requires a real labeled dataset
    to be meaningful -- see that script's docstring.
    """

    def __init__(
        self,
        model,
        thresholds: Optional[RiskThresholds] = None,
        repeat_visit_threshold: int = 2,
    ):
        self.model = model
        self.thresholds = thresholds or RiskThresholds()
        self.repeat_visit_threshold = repeat_visit_threshold

    @classmethod
    def load(cls, path: str | Path, **kwargs) -> "LogisticRiskEngine":
        import joblib

        return cls(model=joblib.load(path), **kwargs)

    def score(self, features: RiskFeatures) -> RiskResult:
        x = featurize(features, self.repeat_visit_threshold)
        proba = float(self.model.predict_proba([x])[0][1])
        score = proba * 100.0

        # Approximate, human-facing breakdown: each active feature's share
        # of the raw logit contribution. This is a post-hoc explanation of
        # an opaque model, not an exact decomposition -- Approach B exists
        # precisely so an explanation doesn't have to be approximate.
        clf = self.model.named_steps.get("clf") if hasattr(self.model, "named_steps") else None
        breakdown: dict[str, float] = {}
        if clf is not None and hasattr(clf, "coef_"):
            active = _active_flags(features, self.repeat_visit_threshold)
            contributions = {
                key: coef * value
                for key, coef, value in zip(FEATURE_ORDER, clf.coef_[0], x)
                if active.get(key) and coef > 0
            }
            total = sum(contributions.values()) or 1.0
            breakdown = {
                FEATURE_LABELS[key]: round(score * (v / total), 1) for key, v in contributions.items()
            }

        return RiskResult(score=score, level=self.thresholds.level_for(score), breakdown=breakdown)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_risk_engine(config) -> RuleRiskEngine | LogisticRiskEngine:
    """Build whichever engine ``config.risk_mode`` asks for, falling back
    to Approach A's defaults if the weighted/ML artifacts referenced in
    config don't exist yet (i.e. before any labeled data has been
    collected) -- the live pipeline should never hard-fail for that reason.
    """
    from .config import resolve_path

    thresholds = config.risk_thresholds
    rvt = config.repeat_visit_threshold

    if config.risk_mode == "weighted":
        weights_path = resolve_path(config.weighted_weights_path)
        if weights_path.exists():
            return RuleRiskEngine(weights=load_weights(weights_path), thresholds=thresholds, repeat_visit_threshold=rvt)
        return RuleRiskEngine(thresholds=thresholds, repeat_visit_threshold=rvt)  # Approach A fallback

    if config.risk_mode == "ml":
        model_path = resolve_path(config.ml_model_path)
        if model_path.exists():
            return LogisticRiskEngine.load(model_path, thresholds=thresholds, repeat_visit_threshold=rvt)
        return RuleRiskEngine(thresholds=thresholds, repeat_visit_threshold=rvt)  # Approach A fallback

    return RuleRiskEngine(thresholds=thresholds, repeat_visit_threshold=rvt)
