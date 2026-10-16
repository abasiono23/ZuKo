from app.categories import Category
from app.insights import engine


def test_snapshot_safe_daily(ctx):
    s = engine.snapshot(ctx)
    assert s.days_until_inflow == 12
    assert s.committed_obligations == 8000
    assert s.discretionary == 28500 - 8000 - 3000
    assert s.safe_daily_spend == round(17500 / 12)
    assert s.income_this_cycle == 15000


def test_food_velocity_alert(ctx):
    res = engine.build_insights(ctx)
    food_alerts = [a for a in res.alerts if a.category == Category.FOOD]
    assert food_alerts and food_alerts[0].kind == "velocity"


def test_pacing_statuses(ctx):
    pacing = {p.category: p for p in engine.category_pacing(ctx)}
    assert pacing[Category.FOOD].spent == 13100
    assert pacing[Category.FOOD].status == "critical"
    assert pacing[Category.PERSONAL_LEISURE].status == "untouched"


def test_weekly_pattern_has_seven_days(ctx):
    week = engine.daily_spend(ctx)
    assert len(week) == 7 and week[-1].date == ctx.today and week[-1].amount == 2100


def test_affordability_tight_purchase(ctx):
    r = engine.affordability(ctx, 12000, "cinema outing")
    assert r.affordable and r.risk_level == "high"
    assert r.remaining_after == 17500 - 12000
    assert 0 < r.suggested_cap <= 17500 / 2


def test_affordability_unaffordable(ctx):
    r = engine.affordability(ctx, 20000)
    assert not r.affordable and r.risk_level == "critical"


def test_affordability_easy(ctx):
    r = engine.affordability(ctx, 500, "snacks")
    assert r.risk_level == "low"


def test_runway_impact(ctx):
    impact = engine.runway_impact(ctx, 3500)
    assert impact.balance_after == 25000
    assert impact.safe_daily_after < impact.safe_daily_before


def test_savings_advice_caps_lock(ctx):
    advice = engine.build_insights(ctx).savings_advice
    assert advice and advice.max_goal_contribution <= 17500 / 3


def test_commitments_exceed_cash(ctx):
    poor = ctx.model_copy(update={"balance": 5000})
    kinds = [a.kind for a in engine.build_insights(poor).alerts]
    assert "runway" in kinds
