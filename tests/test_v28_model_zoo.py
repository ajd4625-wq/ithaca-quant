"""v2.8 model zoo: grouped learning-to-rank with immutable audit boundaries."""
import numpy as np
import pandas as pd
import pytest
from ithaca_quant.model_zoo import (_graded_relevance, _metrics, _train, _prepare,
                                     compare_rank_models, model_catalog)
from ithaca_quant.research_lab import _candidate, asymmetric_conformal_interval


def make_panel(seed=2, n_dates=340, n_stocks=12):
    rng=np.random.default_rng(seed)
    days=pd.bdate_range('2024-01-02', periods=n_dates)
    rows=[]
    for di, day in enumerate(days):
        for i in range(n_stocks):
            # Observable factor has a synthetic relationship to future returns;
            # these are not estimates of actual stock model accuracy.
            strength=(i - n_stocks/2)/6 + rng.normal(0,.07)
            rows.append({'date':day,'label_end':day + pd.offsets.BDay(5),
                        'ticker':f'T{i:02d}',
                        'mom_20':strength,
                        'mom_5_accel':strength/10,
                        'range_252':.5,
                        'target':.03*strength + rng.normal(0,.002)})
    return pd.DataFrame(rows)


def test_catalog_describes_models_and_optional_status():
    df=model_catalog()
    assert {'Model','Family','Distinctive feature','Availability'} <= set(df.columns)
    assert 'LightGBM LambdaMART' in df.Model.values
    assert 'Explainable boosting (EBM)' in df.Model.values
    assert 'RBF nonlinear ridge' in df.Model.values


def test_new_return_forecasters_fit_and_are_finite():
    x=np.linspace(-2,2,150).reshape(-1,1)
    y=.06*np.sin(x[:,0])
    y[-1]=5
    for name in ('Huber robust regression','RBF nonlinear ridge','Median quantile boosting'):
        model=_candidate(name, fast=True)
        model.fit(x,y)
        assert np.isfinite(model.predict(x[:10])).all()


def test_asymmetric_interval_does_not_claim_coverage_without_data():
    lo,hi=asymmetric_conformal_interval([.1,-.2],[.0,.01],min_n=80)
    assert np.isnan(lo).all() and np.isnan(hi).all()
    residuals=np.linspace(-.08,.12,150)
    lo,hi=asymmetric_conformal_interval(residuals,[.01,.03])
    assert (lo<hi).all()
    assert not np.allclose(lo + hi,np.array([.02,.06]))  # deliberately asymmetric


def test_grades_are_within_each_decision_date_and_input_order_invariant():
    df=make_panel(n_dates=3)
    scores=_graded_relevance(df)
    assert scores.min()==0 and scores.max()==4
    shuffled=df.sample(frac=1,random_state=4)
    a=pd.Series(scores,index=df.index)
    b=pd.Series(_graded_relevance(shuffled),index=shuffled.index)
    assert (a.sort_index()==b.sort_index()).all()


def test_preparation_rejects_lookahead_and_duplicate_rows():
    df=make_panel(n_dates=4)
    with pytest.raises(ValueError,match='Duplicate'):
        _prepare(pd.concat([df,df.iloc[[0]]]))
    bad=df.copy()
    bad.loc[bad.index[0],'label_end']=bad.iloc[0].date
    with pytest.raises(ValueError,match='mature after'):
        _prepare(bad)


def test_rank_baseline_and_factor_blend_score_multiple_stocks():
    df=make_panel(n_dates=30)
    df=df.sort_values(['date','ticker'])
    cols=['mom_20','mom_5_accel','range_252']
    for model in ['Ridge (rank baseline)','Histogram rank surrogate','Fixed factor ensemble']:
        fitted=_train(model,df,cols)
        preds=fitted.predict(df[cols].to_numpy(float))
        score=_metrics(df,preds)
        assert score['decision_dates']==30
        assert score['mean_rank_ic']>.5


def test_optional_lambda_rankers_accept_date_groups_if_installed():
    import importlib.util
    df=make_panel(n_dates=12)
    cols=['mom_20','range_252']
    x=df[cols].to_numpy(float)
    for label,package in [('LightGBM LambdaMART','lightgbm'),('XGBoost LambdaMART','xgboost')]:
        if importlib.util.find_spec(package):
            model=_train(label,df,cols)
            score=_metrics(df,model.predict(x))
            assert score['decision_dates']==12
            assert score['mean_rank_ic']>.2


def test_challenge_separates_selection_and_audit():
    panel=make_panel()
    result=compare_rank_models(panel,model_names=['Histogram rank surrogate','Fixed factor ensemble'])
    assert len(result.selection_table)>=2
    assert result.selection_table.iloc[0].Model=='Ridge (rank baseline)'
    assert result.selection_table.decision_dates.max()>=20
    assert not result.qualified or (result.audit_table.decision_dates.min()>=20 and len(result.current_ranks)==12)
    # Editing *audit outcomes* cannot change selection scores/model choice.
    dates=sorted(panel.date.unique())
    threshold=dates[-110]
    changed=panel.copy()
    changed.loc[changed.date>=threshold,'target'] *= -1
    after=compare_rank_models(changed,model_names=['Histogram rank surrogate','Fixed factor ensemble'])
    pd.testing.assert_frame_equal(result.selection_table,after.selection_table)
    assert result.winner==after.winner


def test_short_history_never_selects_new_model():
    out=compare_rank_models(make_panel(n_dates=25))
    assert not out.qualified and out.current_ranks.empty
