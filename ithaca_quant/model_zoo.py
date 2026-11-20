"""Optional quant model zoo: time-purged cross-sectional rank challenges.

Qlib-style cross-sectional factors are ranked within a *signal date*. LightGBM
LambdaMART and XGBoost LambdaMART, when installed, learn those rankings.
A lightweight histogram-boosting rank surrogate runs with the base app.
No candidate changes production forecast output without separate evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib.util import find_spec
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .features import FEATURES, EXTENDED_FEATURES

MODEL_CATALOG = (
    ('Ridge (rank baseline)', 'Ridge', 'Linear factor baseline', 'Built in'),
    ('Histogram rank surrogate', 'Qlib-inspired', 'Nonlinear factor interactions; no extra packages', 'Built in'),
    ('Fixed factor ensemble', 'Ensembling', 'Combines linear and nonlinear scores without tuning blend weights on the audit', 'Built in'),
    ('LightGBM LambdaMART', 'LightGBM', 'Directly optimizes within-date stock rankings', 'lightgbm'),
    ('XGBoost LambdaMART', 'XGBoost', 'Pairwise NDCG ranking with grouped decision dates', 'xgboost'),
    ('Huber robust regression', 'Huber', 'Reduces large-return outlier influence', 'Built in'),
    ('RBF nonlinear ridge', 'Kernel approximation', 'Learns nonlinear factor relationships with limited memory', 'Built in'),
    ('Median quantile boosting', 'Quantile', 'Targets median return rather than squared-error average', 'Built in'),
    ('Explainable boosting (EBM)', 'InterpretML', 'Auditable learned factor-shape curves', 'interpret'),
    ('CatBoost (ordered inputs)', 'CatBoost', 'Preserves time-ordered sample handling', 'catboost'),
)


def model_catalog() -> pd.DataFrame:
    return pd.DataFrame([
        {'Model': name, 'Family': family, 'Distinctive feature': feature,
         'Availability': 'Ready' if req == 'Built in' else
                          ('Optional installed' if find_spec(req) else 'Optional not installed')}
        for name, family, feature, req in MODEL_CATALOG
    ])


@dataclass
class RankZooResult:
    selection_table: pd.DataFrame
    audit_table: pd.DataFrame
    current_ranks: pd.DataFrame
    winner: str
    qualified: bool
    evidence: str


def _prepare(panel: pd.DataFrame, *, asof=None, min_tickers=10):
    required = {'date', 'ticker', 'label_end', 'target'}
    if not required.issubset(panel.columns):
        raise ValueError('Missing required dated ranking panel fields: ' + ', '.join(sorted(required - set(panel.columns))))
    if panel.empty:
        raise ValueError('Ranking panel is empty')
    df = panel.copy()
    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    df['label_end'] = pd.to_datetime(df['label_end'], errors='coerce')
    df['target'] = pd.to_numeric(df['target'], errors='coerce')
    df = df.dropna(subset=['date', 'ticker'])
    if (df.loc[df.label_end.notna(), 'label_end'] <= df.loc[df.label_end.notna(), 'date']).any():
        raise ValueError('Ranking labels must mature after their signal dates')
    if df.duplicated(['date', 'ticker']).any():
        raise ValueError('Duplicate ticker-date observations cannot form independent ranks')
    if asof is not None:
        df = df[df['date'] <= pd.Timestamp(asof)].copy()
    if df.empty:
        raise ValueError('No data at the requested as-of date')
    latest = df.loc[df.date == df.date.max()].copy()
    if latest.ticker.nunique() < min_tickers:
        raise ValueError('Need enough stocks on the latest modeled date')
    cols = [c for c in dict.fromkeys(FEATURES + EXTENDED_FEATURES) if c in df]
    if not cols:
        raise ValueError('No supported historical factors to train on')
    # No future values imputed: only same-row known factors, 0 representing missing.
    df[cols] = df[cols].apply(pd.to_numeric, errors='coerce').replace([np.inf, -np.inf], np.nan).fillna(0).clip(-10000, 10000)
    latest = df.loc[df.date == df.date.max()].copy()
    eligible = df.loc[df.target.notna() & df.label_end.notna() & (df.label_end <= df.date.max())].copy()
    # Bound the *research* training/evaluation load on small Streamlit instances.
    # Stable per-name hashing uses no future returns; full latest-day ranking is retained.
    if eligible.groupby('date').size().max() > 200:
        import hashlib
        ticker_keys = eligible['ticker'].astype(str).map(
            lambda t: int(hashlib.sha256(t.encode('utf-8')).hexdigest()[:12],16))
        eligible = eligible.assign(_ticker_hash=ticker_keys)
        eligible = eligible.sort_values(['date','_ticker_hash','ticker'],kind='mergesort')
        eligible = eligible.groupby('date',sort=False).head(200).drop(columns=['_ticker_hash'])
    eligible = eligible.sort_values(['date','ticker'], kind='mergesort')
    counts = eligible.groupby('date').ticker.transform('nunique')
    eligible = eligible.loc[counts >= min_tickers].copy()
    return eligible, latest, cols


def _graded_relevance(df: pd.DataFrame) -> np.ndarray:
    # Use ranks inside a decision date, never a global distribution threshold.
    rank = df.groupby('date', sort=False)['target'].rank(method='average', pct=True)
    return np.clip(np.ceil(rank.to_numpy() * 5).astype(int) - 1, 0, 4)


class _FixedBlend:
    """Predetermined 50/50 blend; normalizes with training scores only."""
    def __init__(self, linear, nonlinear, levels):
        self.linear = linear
        self.nonlinear = nonlinear
        self.levels = levels

    def predict(self, X):
        a = self.linear.predict(X)
        b = self.nonlinear.predict(X)
        mu_a, sigma_a, mu_b, sigma_b = self.levels
        return .5*(a-mu_a)/sigma_a + .5*(b-mu_b)/sigma_b


def _train(name, frame: pd.DataFrame, columns: list[str]):
    frame = frame.sort_values(['date','ticker'], kind='mergesort')
    x = frame[columns].to_numpy(dtype=float)
    grade = _graded_relevance(frame)
    if name == 'Ridge (rank baseline)':
        fitted = make_pipeline(StandardScaler(), Ridge(alpha=50))
        fitted.fit(x, grade)
    elif name == 'Histogram rank surrogate':
        fitted = HistGradientBoostingRegressor(max_iter=90, max_leaf_nodes=13,
                    max_depth=4, min_samples_leaf=25, l2_regularization=15,
                    early_stopping=False, random_state=42)
        fitted.fit(x, grade)
    elif name == 'Fixed factor ensemble':
        linear = _train('Ridge (rank baseline)', frame, columns)
        nonlinear = _train('Histogram rank surrogate', frame, columns)
        a, b = linear.predict(x), nonlinear.predict(x)
        levels = (float(a.mean()), max(float(a.std()),1e-6),
                  float(b.mean()), max(float(b.std()),1e-6))
        fitted = _FixedBlend(linear, nonlinear, levels)
    elif name == 'LightGBM LambdaMART':
        import lightgbm as lgb
        groups = frame.groupby('date', sort=False).size().to_numpy(dtype=int)
        fitted = lgb.LGBMRanker(objective='lambdarank', n_estimators=90, num_leaves=15,
                   learning_rate=.04, min_child_samples=20, max_depth=5,
                   lambdarank_truncation_level=10, random_state=42, n_jobs=2, verbosity=-1)
        fitted.fit(x, grade, group=groups)
    elif name == 'XGBoost LambdaMART':
        import xgboost as xgb
        qid = pd.factorize(frame['date'], sort=True)[0]
        fitted = xgb.XGBRanker(objective='rank:ndcg', n_estimators=90, max_depth=4,
                   learning_rate=.05, subsample=.85, colsample_bytree=.8,
                   tree_method='hist', random_state=42, n_jobs=2)
        fitted.fit(x, grade, qid=qid)
    else:
        raise ValueError(f'Unsupported ranking model: {name}')
    return fitted


def _metrics(frame: pd.DataFrame, scores, *, min_stocks=10) -> dict:
    data = frame[['date','ticker','target']].copy()
    data['score'] = np.asarray(scores, dtype=float)
    data = data.replace([np.inf,-np.inf],np.nan).dropna(subset=['target','score'])
    ic, lifts, ndcg_values = [], [], []
    for _, day in data.groupby('date'):
        if len(day) < min_stocks or day['target'].nunique() < 2 or day['score'].nunique() < 2:
            continue
        corr = day['score'].corr(day['target'],method='spearman')
        if not np.isfinite(corr):
            continue
        ic.append(float(corr))
        n_top = max(1, int(np.ceil(len(day) * .20)))
        top = day.nlargest(n_top, 'score')
        lifts.append(float(top.target.mean() - day.target.mean()))
        # Normalized discounted cumulative gain based on positive within-date relevance.
        truth = day.target.to_numpy(float)
        rel = pd.Series(truth).rank(method='average',pct=True).to_numpy()
        pred_order = np.argsort(-day.score.to_numpy(float),kind='mergesort')[:n_top]
        perfect = np.argsort(-rel,kind='mergesort')[:n_top]
        discounts = 1/np.log2(np.arange(2,n_top+2))
        score = np.sum((2**(rel[pred_order]*4)-1)*discounts)
        maximum = np.sum((2**(rel[perfect]*4)-1)*discounts)
        ndcg_values.append(float(score/maximum) if maximum>0 else np.nan)
    return {'decision_dates':len(ic), 'ticker_outcomes':len(data),
            'mean_rank_ic':float(np.mean(ic)) if ic else np.nan,
            'top20_excess_lift':float(np.mean(lifts)) if lifts else np.nan,
            'mean_top20_ndcg':float(np.nanmean(ndcg_values)) if ndcg_values else np.nan}


def compare_rank_models(panel: pd.DataFrame, *, asof=None, min_tickers=10,
                        model_names=None, min_dates=20) -> RankZooResult:
    """Select by purged selection dates; replicate on untouched purged audit dates.

    Model outputs are ranking scores, NOT probabilities. No production switch.
    Audit is never used to choose a candidate or tune thresholds.
    """
    eligible, latest, cols = _prepare(panel, asof=asof, min_tickers=min_tickers)
    dates = pd.DatetimeIndex(sorted(eligible.date.unique()))
    none = RankZooResult(pd.DataFrame(),pd.DataFrame(),pd.DataFrame(),'None',False,
                         'Insufficient mature, diverse stock-date samples; no model was promoted.')
    if len(dates) < 310:
        return none
    select_start, audit_start = dates[-220], dates[-110]
    fit = eligible.loc[eligible.label_end < select_start].tail(50000)
    select = eligible.loc[(eligible.date >= select_start) & (eligible.label_end < audit_start)].copy()
    audit = eligible.loc[eligible.date >= audit_start].copy()
    if min(len(fit),len(select),len(audit)) < 300 or min(select.date.nunique(),audit.date.nunique()) < min_dates:
        return none
    names = model_names if model_names is not None else (
        'Ridge (rank baseline)', 'Histogram rank surrogate', 'Fixed factor ensemble',
        'LightGBM LambdaMART', 'XGBoost LambdaMART')
    names = list(dict.fromkeys(['Ridge (rank baseline)', *names]))
    selected_rows, fitted = [], {}
    for name in names:
        try:
            model = _train(name, fit, cols)
            scores = model.predict(select[cols].to_numpy(dtype=float))
            m = _metrics(select, scores, min_stocks=min_tickers)
            selected_rows.append({'Model':name, **m, 'Status':'Evaluated'})
            fitted[name] = model
        except ImportError:
            selected_rows.append({'Model':name,'Status':'Optional dependency missing'})
        except (ValueError, TypeError, FloatingPointError) as exc:
            selected_rows.append({'Model':name,'Status':f'Unavailable ({type(exc).__name__})'})
    selection_table = pd.DataFrame(selected_rows)
    valid = selection_table.loc[selection_table.Status=='Evaluated']
    if 'Ridge (rank baseline)' not in valid.Model.to_list():
        return RankZooResult(selection_table,pd.DataFrame(),pd.DataFrame(),'None',False,
                             'Ranking baseline could not be evaluated; no candidate promoted.')
    base = valid.loc[valid.Model=='Ridge (rank baseline)'].iloc[0]
    challengers = valid.loc[(valid.Model!='Ridge (rank baseline)') &
           (valid.mean_rank_ic > float(base.mean_rank_ic)+.01) &
           (valid.top20_excess_lift > float(base.top20_excess_lift)+.001) &
           (valid.decision_dates >= min_dates)]
    # Selection-only winner; the untouched audit must independently confirm it.
    winner = str(challengers.sort_values(['mean_rank_ic','top20_excess_lift'],ascending=False).iloc[0].Model) if len(challengers) else 'Ridge (rank baseline)'
    if winner == 'Ridge (rank baseline)':
        return RankZooResult(selection_table,pd.DataFrame(),pd.DataFrame(),winner,False,
            'No candidate outperformed the linear baseline on both ranking metrics in the purged selection period.')
    training_audit = eligible.loc[eligible.label_end < audit_start].tail(60000)
    audit_rows=[]
    try:
        for name in ('Ridge (rank baseline)', winner):
            model = _train(name, training_audit, cols)
            metrics = _metrics(audit,model.predict(audit[cols].to_numpy(dtype=float)),min_stocks=min_tickers)
            audit_rows.append({'Model':name, **metrics})
        baseline, candidate = audit_rows
        qualified = (candidate['decision_dates'] >= min_dates and
                     candidate['mean_rank_ic'] > baseline['mean_rank_ic'] + .005 and
                     candidate['top20_excess_lift'] > baseline['top20_excess_lift'] + .0005 and
                     candidate['top20_excess_lift'] > 0)
        result = pd.DataFrame(audit_rows)
        if not qualified:
            return RankZooResult(selection_table,result,pd.DataFrame(),winner,False,
                'Selection winner failed its untouched audit gate. Existing rankings retained.')
        final = _train(winner,eligible.tail(60000),cols)
        scores = final.predict(latest[cols].to_numpy(dtype=float))
        ranked = latest[['ticker']].copy()
        ranked['rank_score'] = scores
        ranked = ranked.sort_values(['rank_score','ticker'],ascending=[False,True]).reset_index(drop=True)
        ranked['research_rank'] = np.arange(1,len(ranked)+1)
        return RankZooResult(selection_table,result,ranked,winner,True,
               'Ranking challenger passed independent purged selection and audit. Research-sidecar only; no live accuracy claim.')
    except (ImportError, ValueError, TypeError, FloatingPointError) as exc:
        return RankZooResult(selection_table,pd.DataFrame(audit_rows),pd.DataFrame(),winner,False,
                             f'Audit could not finish ({type(exc).__name__}); unchanged production.')
