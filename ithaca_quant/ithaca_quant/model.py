"""Ensemble with a chronological label-availability boundary."""
from dataclasses import dataclass
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor

from .config import MAX_AGENTS, improved_accuracy, cross_sectional_target_enabled
from .features import (FEATURES, FUNDAMENTAL_FEATURES, NEWS_FEATURES, REGIME_FEATURES,
                       EXTENDED_FEATURES)
from .probability import annotate_probabilities
from .earnings_expectations import EARNINGS_FEATURES


@dataclass
class Ensemble:
    boosted: HistGradientBoostingRegressor
    forest: RandomForestRegressor
    feature_names: tuple[str, ...] = tuple(FEATURES)
    # Constant added back when the model was trained on a same-day-demeaned label.
    offset: float = 0.0

    def predict(self, features: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        x = features[list(self.feature_names)].to_numpy(dtype=float)
        p1 = self.boosted.predict(x)
        p2 = self.forest.predict(x)
        # Regression models can extrapolate wildly; these are bounded model outputs.
        forecast = np.clip((p1 + p2) / 2 + self.offset, -0.5, 0.5)
        disagreement = abs(p1 - p2)
        return forecast, disagreement


def training_snapshot(panel: pd.DataFrame, asof: pd.Timestamp, window_years: int = 4) -> pd.DataFrame:
    """Only labels fully observed strictly before the prediction's as-of date."""
    left = pd.Timestamp(asof) - pd.DateOffset(years=window_years)
    train = panel.loc[
        (panel["date"] >= left) & (panel["date"] < asof) &
        (panel["label_end"] < asof) & panel["target"].notna()
    ].copy()
    return train


MIN_SHRINKAGE = 0.15  # keeps the forecast ordering (a zero factor would tie every stock)


def robust_target(y: np.ndarray) -> np.ndarray:
    """Winsorize a training target at its own 0.5% / 99.5% quantiles.

    A fixed +/-80% clip barely touches 20-day excess returns, so a handful of
    takeover / crash events can dominate squared-error fits. Quantile
    winsorization is data-scaled (works for 1-day and 60-day horizons alike).
    """
    y = np.asarray(y, dtype=float)
    if not improved_accuracy() or len(y) < 200:
        return np.clip(y, -0.8, 0.8)
    low, high = np.nanquantile(y, [0.005, 0.995])
    return np.clip(y, max(low, -0.8), min(high, 0.8))


def shrinkage_factor(truth, predicted) -> float:
    """Out-of-sample slope of realized on predicted excess return, clipped to [0.15, 1].

    Tree ensembles fit to noisy returns are over-dispersed; predictions whose
    realized slope is below one should be scaled toward zero. Never amplifies.
    Multiplying by a positive constant leaves every ranking unchanged.
    """
    if not improved_accuracy():
        return 1.0
    truth = np.asarray(truth, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    ok = np.isfinite(truth) & np.isfinite(predicted)
    if ok.sum() < 50:
        return 1.0
    denominator = float(np.dot(predicted[ok], predicted[ok]))
    if denominator <= 1e-12:
        return 1.0
    slope = float(np.dot(predicted[ok], truth[ok]) / denominator)
    return float(np.clip(slope, MIN_SHRINKAGE, 1.0))


def _selection_split(train: pd.DataFrame):
    """Embargoed chronological (early, holdout) split, or None if too short."""
    dates = train["date"].sort_values().unique()
    if len(dates) < 300:
        return None
    cutoff = pd.Timestamp(dates[len(dates) - 100])
    early = train.loc[(train["date"] < cutoff) & (train["label_end"] < cutoff)]
    holdout = train.loc[train["date"] >= cutoff]
    if len(early) < 350 or len(holdout) < 50:
        return None
    return early, holdout


def estimate_shrinkage(train: pd.DataFrame, features: tuple[str, ...], fast: bool = False) -> float:
    """Shrink factor learned on the embargoed holdout (1.0 if there is too little history)."""
    if not improved_accuracy():
        return 1.0
    split = _selection_split(train)
    if split is None:
        return 1.0
    early, holdout = split
    try:
        model = fit_ensemble(early, fast=True, features=tuple(features))
    except ValueError:
        return 1.0
    predicted, _ = model.predict(holdout)
    return shrinkage_factor(robust_target(holdout["target"].to_numpy(dtype=float)), predicted)


def fit_ensemble(train: pd.DataFrame, fast: bool = False,
                 features: tuple[str, ...] | None = None, target_col: str = "target") -> Ensemble:
    if len(train) < 350 or train["date"].nunique() < 100:
        raise ValueError("Not enough training history. Try more years of data.")
    if len(train) > 120_000:
        train = train.sample(n=120_000, random_state=42).sort_values("date")
    columns = tuple(features or FEATURES)
    x = train[list(columns)].to_numpy(dtype=float)
    y = train[target_col].to_numpy(dtype=float)
    # Average gap between the raw and demeaned label is restored at prediction time,
    # so forecasts stay on the SPY-relative scale.
    offset = 0.0 if target_col == "target" else float(np.nanmean(
        train["target"].to_numpy(dtype=float) - y))
    # Truncation reduces sensitivity to extraordinary historical jumps.
    y = robust_target(y)
    boosted = HistGradientBoostingRegressor(
        learning_rate=0.045, max_iter=40 if fast else 90,
        max_leaf_nodes=11, max_depth=4, min_samples_leaf=25,
        l2_regularization=5, random_state=42,
        early_stopping=False,
    )
    forest = RandomForestRegressor(
        n_estimators=30 if fast else 90, max_depth=7,
        min_samples_leaf=12, max_features=0.7,
        random_state=21, n_jobs=MAX_AGENTS,
    )
    boosted.fit(x, y)
    forest.fit(x, y)
    return Ensemble(boosted, forest, columns, offset)


def per_date_rank_ic(dates, predicted, truth, min_names: int = 5) -> pd.Series:
    """Spearman correlation of prediction and outcome for every decision date."""
    frame = pd.DataFrame({"d": np.asarray(dates), "p": np.asarray(predicted, float),
                          "y": np.asarray(truth, float)}).dropna()
    frame = frame.loc[frame.groupby("d")["p"].transform("size") >= min_names]
    if frame.empty:
        return pd.Series(dtype=float)
    frame["rp"] = frame.groupby("d")["p"].rank()
    frame["ry"] = frame.groupby("d")["y"].rank()
    for c in ("rp", "ry"):
        frame[c] = frame[c] - frame.groupby("d")[c].transform("mean")
    num = (frame["rp"] * frame["ry"]).groupby(frame["d"]).sum()
    den = np.sqrt((frame["rp"] ** 2).groupby(frame["d"]).sum() * (frame["ry"] ** 2).groupby(frame["d"]).sum())
    return (num / den.replace(0, np.nan)).dropna()


def mean_rank_ic(dates, predicted, truth, min_names: int = 5) -> float:
    """Average per-date Spearman correlation (the stock-ranking skill measure)."""
    ic = per_date_rank_ic(dates, predicted, truth, min_names)
    return float(ic.mean()) if len(ic) else float("nan")


def choose_target_mode(train: pd.DataFrame, features: tuple[str, ...], fast: bool = False):
    """Pick the raw SPY-relative label or the same-day-demeaned label.

    Uses the same independent blocks as feature selection: fit early, learn the
    forecast scale on a middle block, compare on the LAST block. The demeaned
    label is adopted only if it ranks stocks better (mean per-date rank IC up by
    >= 0.01 and a paired t-statistic >= 2 across dates) without worsening absolute error on the true label by more than 1%.
    Returns (mode, scale, note); mode is 'raw' or 'cs'.
    """
    raw = ("raw", None, "Raw SPY-relative training label")
    if not cross_sectional_target_enabled() or "target_cs" not in train:
        return raw
    dates = train["date"].sort_values().unique()
    if len(dates) < 390:
        return raw
    scale_start, selection_start = map(pd.Timestamp, (dates[-180], dates[-90]))
    early = train.loc[(train["date"] < scale_start) & (train["label_end"] < scale_start)]
    calibration = train.loc[(train["date"] >= scale_start) & (train["date"] < selection_start) &
                            (train["label_end"] < selection_start)]
    selection = train.loc[train["date"] >= selection_start]
    if min(len(calibration), len(selection)) < 50 or len(early) < 350:
        return raw
    results = {}
    for mode, column in (("raw", "target"), ("cs", "target_cs")):
        try:
            fitted = fit_ensemble(early, fast=True, features=tuple(features), target_col=column)
        except ValueError:
            return raw
        scale = shrinkage_factor(calibration["target"].to_numpy(float), fitted.predict(calibration)[0])
        predicted = fitted.predict(selection)[0]
        mae = float(np.mean(np.abs(selection["target"].to_numpy(float) - predicted * scale)))
        ic_series = per_date_rank_ic(selection["date"], predicted, selection["target"])
        results[mode] = (mae, float(ic_series.mean()) if len(ic_series) else float("nan"), scale, ic_series)
    (raw_mae, raw_ic, raw_scale, raw_series), (cs_mae, cs_ic, cs_scale, cs_series) = results["raw"], results["cs"]
    # Paired per-date IC difference must be statistically distinguishable from zero
    # (t >= 2): with ~90 selection dates a fixed margin alone sits inside sampling noise.
    paired = (cs_series - raw_series).dropna()
    t_stat = (float(paired.mean() / (paired.std(ddof=1) / np.sqrt(len(paired))))
              if len(paired) >= 30 and paired.std(ddof=1) > 0 else 0.0)
    if (np.isfinite(cs_ic) and np.isfinite(raw_ic) and cs_ic >= raw_ic + 0.01
            and t_stat >= 2.0 and cs_mae <= raw_mae * 1.01):
        return ("cs", cs_scale,
                f"Same-day-demeaned label selected (rank IC {raw_ic:+.3f} -> {cs_ic:+.3f}, t={t_stat:.1f}, on independent block)")
    return ("raw", None, f"Raw label retained (demeaned rank IC {cs_ic:+.3f} vs raw {raw_ic:+.3f}, t={t_stat:.1f})")


def _choose_with_scale(train: pd.DataFrame, asof, fast=False):
    """Purged three-way feature evaluation with a separate scale-fit period.

    A model is fit before the calibration period; its scale is learned there,
    then competing feature groups are compared in a strictly LATER period.
    The later scores never set their own scale. This prevents selecting the
    best-looking in-sample scale/feature pair on the same labels.
    """
    base = tuple(FEATURES)
    dates = train["date"].sort_values().unique()
    if not improved_accuracy():
        return _legacy_choose_with_scale(train, asof, fast)
    if len(dates) < 390:
        return base, "Price/volume baseline: insufficient independent scale and selection windows", None, 1.0
    scale_start, selection_start = map(pd.Timestamp, (dates[-180], dates[-90]))
    early = train.loc[(train["date"] < scale_start) & (train["label_end"] < scale_start)]
    calibration = train.loc[(train["date"] >= scale_start) &
                            (train["date"] < selection_start) &
                            (train["label_end"] < selection_start)]
    selection = train.loc[train["date"] >= selection_start]
    if min(len(early), len(calibration), len(selection)) < 50 or len(early) < 350:
        return base, "Price/volume baseline: insufficient purged independent samples", None, 1.0

    groups = []
    if all(f in train for f in REGIME_FEATURES):
        groups.append((tuple(REGIME_FEATURES), 'Observable SPY regime indicators', .01))
    if all(f in train for f in EXTENDED_FEATURES):
        groups.append((tuple(EXTENDED_FEATURES), 'Extended price/liquidity/cross-sectional features', .01))
    issuer_min = max(1, int(np.ceil(train['ticker'].nunique() * .10)))
    if all(f in train for f in EARNINGS_FEATURES):
        if (early.loc[early['earnings_surprise_available'] > 0, 'date'].nunique() >= 100 and
                selection.loc[selection['earnings_surprise_available'] > 0, 'date'].nunique() >= 20):
            groups.append((tuple(EARNINGS_FEATURES), 'Timestamped analyst EPS surprise', .01))
    if all(f in train for f in FUNDAMENTAL_FEATURES):
        if (early.loc[early['sec_available'] > 0, 'ticker'].nunique() >= issuer_min and
                early['sec_available'].sum() >= 100 and selection['sec_available'].sum() >= 25):
            groups.append((tuple(FUNDAMENTAL_FEATURES), 'Dated SEC quarterly filings', .01))
    if all(f in train for f in NEWS_FEATURES):
        if (early.loc[early['news_available'] > 0, 'ticker'].nunique() >= issuer_min and
                early.loc[early['news_available'] > 0, 'date'].nunique() >= 65 and
                selection.loc[selection['news_available'] > 0, 'date'].nunique() >= 25):
            groups.append((tuple(NEWS_FEATURES), 'Timestamped news archive', .02))

    calibrate_y = calibration['target'].to_numpy(dtype=float)
    select_y = selection['target'].to_numpy(dtype=float)
    def score_group(cols):
        fitted = fit_ensemble(early, fast=True, features=cols)
        predicted_cal, _ = fitted.predict(calibration)
        scale = shrinkage_factor(calibrate_y, predicted_cal)
        predicted_selection, _ = fitted.predict(selection)
        error = float(np.mean(np.abs(select_y - predicted_selection * scale)))
        return error, scale

    baseline_mae, baseline_scale = score_group(base)
    best_error, best_scale, best_cols = baseline_mae, baseline_scale, base
    best_note = 'Price-only model retained: no new evidence improved independent selection MAE'
    winners = []
    for additions, name, threshold in groups:
        error, scale = score_group(base + additions)
        if np.isfinite(error) and error < baseline_mae * (1.0 - threshold):
            winners.append((additions, name, threshold))
            if error < best_error:
                best_error, best_scale, best_cols = error, scale, base + additions
                best_note = 'Price/volume + ' + name + ' passed independent chronological selection'
    # More complex feature combinations are considered only if each group won alone.
    from itertools import combinations
    for left, right in combinations(winners, 2):
        additions = left[0] + right[0]
        threshold = max(left[2], right[2])
        error, scale = score_group(base + additions)
        if np.isfinite(error) and error < baseline_mae * (1 - threshold) and error < best_error:
            best_error, best_scale, best_cols = error, scale, base + additions
            best_note = 'Price/volume + ' + left[1] + ' + ' + right[1] + ' passed independent chronological selection'
    return best_cols, best_note, (baseline_mae, best_error), best_scale


def _legacy_choose_with_scale(train: pd.DataFrame, asof, fast=False):
    """Conservative opt-out when ITHACA_LEGACY_MODEL=1 is set."""
    base = tuple(FEATURES)
    split = _selection_split(train)
    if split is None:
        return base, 'Legacy price-only baseline (insufficient history)', None, 1.0
    early, holdout = split
    candidate_groups = []
    if all(f in train for f in REGIME_FEATURES):
        candidate_groups.append((tuple(REGIME_FEATURES), 'Observable SPY regime indicators'))
    if all(f in train for f in FUNDAMENTAL_FEATURES) and early['sec_available'].sum() >= 100 and holdout['sec_available'].sum() >= 25:
        candidate_groups.append((tuple(FUNDAMENTAL_FEATURES), 'Dated SEC quarterly filings'))
    if all(f in train for f in NEWS_FEATURES) and early['news_available'].sum() >= 65 and holdout['news_available'].sum() >= 25:
        candidate_groups.append((tuple(NEWS_FEATURES), 'Timestamped news archive'))
    basic = fit_ensemble(early, fast=True, features=base)
    truth = holdout['target'].to_numpy(float)
    base_err = float(np.mean(abs(truth - basic.predict(holdout)[0])))
    best_cols, best_err = base, base_err
    for extras, _ in candidate_groups:
        model = fit_ensemble(early, fast=True, features=base + extras)
        error = float(np.mean(abs(truth - model.predict(holdout)[0])))
        if error < .98 * base_err and error < best_err:
            best_cols, best_err = base + extras, error
    return best_cols, 'Legacy feature selection', (base_err, best_err), 1.0

def choose_evidence_features(train: pd.DataFrame, asof, fast=False):
    """(features, note, (baseline_mae, selected_mae) | None); see _choose_with_scale."""
    return _choose_with_scale(train, asof, fast=fast)[:3]


def choose_financial_features(train: pd.DataFrame, asof, fast=False):
    """Backwards-compatible alias for SEC/news evidence-aware feature selection."""
    return choose_evidence_features(train, asof, fast=fast)


def forecast_asof(panel: pd.DataFrame, asof: pd.Timestamp, fast: bool = False,
                  boom_return: float = 0.20, enhanced: bool = False) -> pd.DataFrame:
    train = training_snapshot(panel, asof)
    # Large-universe scans can create millions of overlapping examples.
    # Stratified-by-time random sampling bounds training memory and runtime.
    # Sampling is from already-mature, historical labels only.
    if len(train) > 120_000:
        train = train.sample(n=120_000, random_state=42).sort_values("date")
    feature_set, selection_note, holdout_maes, shrink = _choose_with_scale(train, asof, fast=fast)
    target_mode, mode_scale, mode_note = choose_target_mode(train, feature_set, fast=fast)
    if target_mode == "cs":
        shrink = mode_scale
    ensemble = fit_ensemble(train, fast=fast, features=feature_set,
                            target_col="target_cs" if target_mode == "cs" else "target")
    current = panel.loc[panel["date"] == asof].copy()
    current["target_mode"] = target_mode
    current["target_mode_note"] = mode_note
    if current.empty:
        raise ValueError("No feature rows for the latest available session.")
    forecast, disagreement = ensemble.predict(current)
    forecast = forecast * shrink
    current["forecast_shrinkage"] = shrink
    current["selected_model"] = "Existing ensemble"
    current["lab_calibration_n"] = 0
    current["lab_mae"] = np.nan
    current["lab_zero_mae"] = np.nan
    current["lab_interval_low"] = np.nan
    current["lab_interval_high"] = np.nan
    current["lab_explanation"] = ""
    current["lab_diagnostic"] = "Run enhanced model comparison to audit candidates and uncertainty."
    if enhanced:
        from .research_lab import fit_validated_forecaster
        lab = fit_validated_forecaster(train, current, feature_set, fast=fast)
        if lab.calibration_n > 0:  # otherwise the lab fell back; keep the calibrated ensemble
            forecast = lab.forecast  # already calibrated on its own validation block
            current["forecast_shrinkage"] = lab.shrinkage
        current["selected_model"] = lab.model_name
        current["lab_calibration_n"] = lab.calibration_n
        current["lab_mae"] = lab.calibration_mae
        current["lab_zero_mae"] = lab.zero_baseline_mae
        current["lab_interval_low"] = lab.interval_low
        current["lab_interval_high"] = lab.interval_high
        current["lab_explanation"] = "; ".join(lab.explanation)
        current["lab_diagnostic"] = lab.diagnostic
    current["forecast_excess"] = forecast
    current["model_disagreement"] = disagreement
    current["feature_selection"] = selection_note
    current["uses_sec_filings"] = "sec_revenue_yoy" in feature_set
    current["uses_news_history"] = "news_sentiment_7d" in feature_set
    current["filing_tech_holdout_mae"] = holdout_maes[0] if holdout_maes else np.nan
    current["filing_model_holdout_mae"] = holdout_maes[1] if holdout_maes else np.nan
    current = annotate_probabilities(current, train, boom_return=boom_return)
    return current.sort_values("forecast_excess", ascending=False).reset_index(drop=True)
