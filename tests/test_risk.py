from contextguard.risk import (
    FEATURE_ORDER,
    BASELINES,
    LogisticRiskEngine,
    RiskFeatures,
    RuleRiskEngine,
    derive_weights_from_model,
    featurize,
)


def make_features(**overrides):
    defaults = dict(
        identity_known=True,
        zone_kind=None,
        after_hours=False,
        dwell_seconds=0.0,
        is_loitering=False,
        repeat_visit_count=0,
        abnormal_transition=False,
    )
    defaults.update(overrides)
    return RiskFeatures(**defaults)


# -- Approach A: rule-based ------------------------------------------------

def test_rule_engine_matches_hand_sum_for_the_worked_example():
    features = make_features(
        identity_known=False, zone_kind="restricted", after_hours=True,
        dwell_seconds=47, is_loitering=True, repeat_visit_count=2,
    )
    result = RuleRiskEngine().score(features)
    assert result.score == 30 + 20 + 15 + 12 + 10  # restricted+after_hours+loitering+unknown+repeat
    assert result.level == "critical"
    assert set(result.breakdown) == {
        "restricted-zone entry", "unusual hour", "prolonged presence", "unknown identity", "repeated entry",
    }


def test_rule_engine_zero_for_known_person_in_normal_zone_daytime():
    result = RuleRiskEngine().score(make_features(identity_known=True, zone_kind="normal"))
    assert result.score == 0
    assert result.level == "low"


def test_rule_engine_score_clamped_to_100():
    features = make_features(
        identity_known=False, zone_kind="restricted", after_hours=True,
        is_loitering=True, repeat_visit_count=5, abnormal_transition=True,
    )
    weights = {k: 60 for k in FEATURE_ORDER}
    assert RuleRiskEngine(weights=weights).score(features).score == 100


# -- baselines ---------------------------------------------------------

def test_baselines_behave_as_specified():
    unknown_restricted = make_features(identity_known=False, zone_kind="restricted")
    known_restricted = make_features(identity_known=True, zone_kind="restricted")
    unknown_normal = make_features(identity_known=False, zone_kind="normal")

    assert BASELINES["baseline_1_person_detected"](known_restricted) is True
    assert BASELINES["baseline_2_unknown_person"](known_restricted) is False
    assert BASELINES["baseline_2_unknown_person"](unknown_normal) is True
    assert BASELINES["baseline_3_unknown_restricted"](unknown_normal) is False
    assert BASELINES["baseline_3_unknown_restricted"](unknown_restricted) is True


# -- featurization -------------------------------------------------------

def test_featurize_matches_feature_order():
    vec = featurize(
        make_features(
            identity_known=False, zone_kind="restricted", after_hours=True,
            is_loitering=True, repeat_visit_count=3, abnormal_transition=True,
        )
    )
    assert len(vec) == len(FEATURE_ORDER) == 6
    assert vec == [1.0, 1.0, 1.0, 1.0, 1.0, 1.0]


def test_featurize_repeat_visit_respects_threshold():
    below = featurize(make_features(repeat_visit_count=1), repeat_visit_threshold=2)
    at = featurize(make_features(repeat_visit_count=2), repeat_visit_threshold=2)
    assert below[FEATURE_ORDER.index("repeat_visit")] == 0.0
    assert at[FEATURE_ORDER.index("repeat_visit")] == 1.0


# -- Approach B: weights derived from a model, not invented -------------

def test_derive_weights_from_model_ranks_and_bounds():
    # restricted_zone's coefficient is largest -> should get the most points.
    weights = derive_weights_from_model([2.0, 1.0, 0.0, -1.0, 0.5, 0.5], points_budget=100)
    assert weights["restricted_zone"] == max(weights.values())
    assert abs(sum(weights.values()) - 100) <= 3  # rounding, not exact due to integer points
    assert weights["unknown_identity"] == 0  # negative coefficient floored, not negative points


def test_derive_weights_from_model_rejects_all_nonpositive():
    import pytest

    with pytest.raises(ValueError):
        derive_weights_from_model([-1.0, -2.0, 0.0, 0.0, 0.0, 0.0])


# -- Approach C: logistic regression wiring (synthetic data, not a real eval) --

def test_logistic_risk_engine_scores_restricted_higher_on_synthetic_fit():
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    rng = np.random.default_rng(0)
    X = rng.integers(0, 2, size=(200, 6)).astype(float)
    y = (X[:, FEATURE_ORDER.index("restricted_zone")] > 0.5).astype(int)

    pipeline = Pipeline([("scaler", StandardScaler()), ("clf", LogisticRegression())])
    pipeline.fit(X, y)

    engine = LogisticRiskEngine(pipeline)
    high = engine.score(make_features(identity_known=True, zone_kind="restricted"))
    low = engine.score(make_features(identity_known=True, zone_kind="normal"))
    assert high.score > low.score
