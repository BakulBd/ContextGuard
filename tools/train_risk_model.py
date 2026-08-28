"""Train Approach C (logistic regression) on labeled risk-feature rows,
and derive Approach B's interpretable point weights from it -- so
those weights come from data instead of being hand-picked.

This is the Week 5-6 step in the project plan and needs a real labeled
dataset to mean anything. Workflow:

    1. Run the pipeline against staged scenarios for a while so the
       event store has a mix of restricted/normal, day/night,
       loitering/brief-visit events.
    2. python tools/train_risk_model.py export data/contextguard.db data/labeling_template.csv
    3. Open the CSV, fill in `should_alert` by hand for each row
       (1 = a human reviewing this event would want an alert, 0 = not).
    4. python tools/train_risk_model.py train data/labeling_template.csv

Step 4 prints a held-out precision/recall report, writes the trained
sklearn Pipeline to data/risk_model.joblib (Approach C), and writes the
derived point weights to data/risk_weights.json (Approach B).
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from contextguard.events import EventStore
from contextguard.risk import FEATURE_ORDER, derive_weights_from_model, save_weights


def export_labeling_template(db_path: str, out_csv: str) -> None:
    store = EventStore(db_path)
    events = store.query(limit=100_000, order="asc")
    out_path = Path(out_csv)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["event_id", "timestamp", "narrative", *FEATURE_ORDER, "should_alert"])
        for e in events:
            tags = set(e.behavior)
            writer.writerow(
                [
                    e.event_id,
                    e.timestamp,
                    e.narrative,
                    1 if e.zone_kind == "restricted" else 0,
                    1 if "after_hours" in tags else 0,
                    1 if "loitering" in tags else 0,
                    1 if e.identity == "unknown" else 0,
                    1 if "repeated_entry" in tags else 0,
                    1 if "abnormal_transition" in tags else 0,
                    "",  # should_alert -- fill in by hand, 0 or 1
                ]
            )
    print(f"Wrote {len(events)} rows to {out_csv}.")
    print("Fill in the 'should_alert' column (0 or 1) for each row, then run the 'train' command.")


def train(labeled_csv: str, weights_out: str = "data/risk_weights.json", model_out: str = "data/risk_model.joblib") -> None:
    import joblib
    import pandas as pd
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import classification_report
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    df = pd.read_csv(labeled_csv)
    missing = [c for c in [*FEATURE_ORDER, "should_alert"] if c not in df.columns]
    if missing:
        raise ValueError(f"labeled CSV is missing columns: {missing}")

    df = df.dropna(subset=["should_alert"])
    if len(df) < 20:
        raise ValueError(
            f"only {len(df)} labeled rows -- Approach C needs real staged-scenario data "
            "(see the project proposal's dataset strategy), not a handful of rows. "
            "Collect more scenarios and re-export before training."
        )

    X = df[FEATURE_ORDER].values
    y = df["should_alert"].astype(int).values

    stratify = y if len(set(y)) > 1 else None
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.25, random_state=7, stratify=stratify)

    pipeline = Pipeline([("scaler", StandardScaler()), ("clf", LogisticRegression(max_iter=1000))])
    pipeline.fit(X_train, y_train)

    print("Held-out evaluation:")
    print(classification_report(y_test, pipeline.predict(X_test), zero_division=0))

    model_path = Path(model_out)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, model_path)
    print(f"Saved trained model (Approach C) -> {model_out}")

    coefficients = pipeline.named_steps["clf"].coef_[0].tolist()
    weights = derive_weights_from_model(coefficients)
    save_weights(weights, weights_out)
    print(f"Derived Approach B point weights -> {weights_out}: {weights}")
    print("\nSet risk_mode: weighted or risk_mode: ml in config.yaml to use these.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_export = sub.add_parser("export", help="export a labeling template CSV from the event store")
    p_export.add_argument("db_path")
    p_export.add_argument("out_csv")

    p_train = sub.add_parser("train", help="train Approach C and derive Approach B from a labeled CSV")
    p_train.add_argument("labeled_csv")
    p_train.add_argument("--weights-out", default="data/risk_weights.json")
    p_train.add_argument("--model-out", default="data/risk_model.joblib")

    args = parser.parse_args()
    if args.cmd == "export":
        export_labeling_template(args.db_path, args.out_csv)
    elif args.cmd == "train":
        train(args.labeled_csv, args.weights_out, args.model_out)


if __name__ == "__main__":
    main()
