"""Demand forecast – predicts weekly units per product for the next intake period.

Method: gradient-boosted regression trees (scikit-learn) trained with quantile loss
at the 10th, 50th and 90th percentiles, giving a central forecast and an 80 % range.
It is a *direct multi-horizon* model: each training row asks "standing at week o,
how many units of product p will sell in week o+h?" for h = 1..16, using only
information available at week o (no look-ahead).

Features (no personal data):
  horizon h · week-of-year (sin/cos) of the target week · weeks until the next intake
  (September or January) · units in the same week last year (lag 52, and a 3-week
  smoothed version) · mean units in the 4 weeks before the origin · the same mean one
  year earlier · new verified sign-ups in the 4 weeks before the origin · price ·
  number of bundles containing the product · category (one-hot) · year-on-year growth.

The target is normalised: the model learns  units / (last year's units for that week ×
recent growth), then multiplies back. Tree models cannot extrapolate above values they
have seen, so learning a ratio lets the forecast follow a growing business.

Evaluation: back-test on the most recent completed intake period, training only on
data before it, compared with the seasonal-naive baseline "same weeks last intake".
"""
import math
from collections import defaultdict
from datetime import date, timedelta

import numpy as np
from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from sklearn.ensemble import GradientBoostingRegressor

from accounts.models import User
from catalog.models import Category, Product
from orders.models import OrderLine, OrderStatus

from .models import ModelRun, ProductForecast

QUANTILES = (0.1, 0.5, 0.9)
MAX_H = 16
GBR_PARAMS = dict(n_estimators=250, max_depth=3, learning_rate=0.05, subsample=0.8, min_samples_leaf=8, random_state=42)


def monday(d):
    return d - timedelta(days=d.weekday())


def intake_dates(year):
    return [date(year, 1, 8), date(year, 9, 14)]


def weeks_to_next_intake(d):
    candidates = [x for y in (d.year, d.year + 1) for x in intake_dates(y) if x >= d - timedelta(days=21)]
    nxt = min(candidates)
    return (nxt - d).days / 7.0


def next_intake_period(today):
    """The selling period around the next intake: 5 weeks before to 1 week after."""
    candidates = sorted(x for y in (today.year, today.year + 1) for x in intake_dates(y) if x - timedelta(days=35) > today)
    nxt = candidates[0]
    start = monday(nxt - timedelta(days=35))
    end = monday(nxt + timedelta(days=7)) + timedelta(days=6)
    return start, end, nxt


def last_completed_period(today):
    candidates = sorted(x for y in (today.year - 1, today.year) for x in intake_dates(y) if x + timedelta(days=14) <= today)
    last = candidates[-1]
    start = monday(last - timedelta(days=35))
    end = monday(last + timedelta(days=7)) + timedelta(days=6)
    return start, end, last


class Data:
    """Weekly units per product (bundle components included, cancelled orders excluded)."""

    def __init__(self):
        rows = (OrderLine.objects.exclude(order__status=OrderStatus.CANCELLED)
                .filter(product__isnull=False).values_list("product_id", "order__created_at", "quantity"))
        self.units = defaultdict(lambda: defaultdict(int))
        first = None
        for pid, created, q in rows:
            w = monday(timezone.localtime(created).date())
            self.units[pid][w] += q
            first = w if first is None or w < first else first
        self.first_week = first
        self.signups = defaultdict(int)
        for d, c in (User.objects.filter(role="customer").values_list("date_joined__date").annotate(c=Count("id"))):
            self.signups[monday(d)] += c
        self.total = defaultdict(int)
        for pid, weeks in self.units.items():
            for w, q in weeks.items():
                self.total[w] += q
        self._growth = {}
        self.products = list(Product.objects.select_related("category").prefetch_related("bundle_items"))
        self.cat_ids = list(Category.objects.values_list("pk", flat=True))

    def u(self, pid, w):
        return self.units[pid].get(w, 0)

    def mean_before(self, pid, origin, n=4):
        return sum(self.u(pid, origin - timedelta(weeks=i)) for i in range(0, n)) / n

    def signups_before(self, origin, n=4):
        return sum(self.signups.get(origin - timedelta(weeks=i), 0) for i in range(0, n))

    def growth(self, origin, n=12):
        """Year-on-year growth of total units over the n weeks before the origin."""
        if origin in self._growth:
            return self._growth[origin]
        now = sum(self.total.get(origin - timedelta(weeks=i), 0) for i in range(n))
        before = sum(self.total.get(origin - timedelta(weeks=52 + i), 0) for i in range(n))
        g = min(3.0, max(0.5, (now + 10) / (before + 10)))
        self._growth[origin] = g
        return g

    def scale(self, p, origin, h):
        """Seasonal-naive level used to normalise the target: last year's units for the
        same week (3-week smoothed) × recent year-on-year growth."""
        t = origin + timedelta(weeks=h)
        lag52s = sum(self.u(p.pk, t - timedelta(weeks=k)) for k in (51, 52, 53)) / 3
        return max(1.0, lag52s * self.growth(origin))

    def features(self, p, origin, h):
        t = origin + timedelta(weeks=h)
        woy = t.isocalendar()[1]
        lag52 = self.u(p.pk, t - timedelta(weeks=52))
        lag52s = (self.u(p.pk, t - timedelta(weeks=51)) + lag52 + self.u(p.pk, t - timedelta(weeks=53))) / 3
        recent = self.mean_before(p.pk, origin)
        recent_ly = self.mean_before(p.pk, origin - timedelta(weeks=52))
        row = [h, math.sin(2 * math.pi * woy / 52), math.cos(2 * math.pi * woy / 52), weeks_to_next_intake(t),
               lag52, lag52s, recent, recent_ly, self.signups_before(origin), self.growth(origin),
               recent / max(1.0, recent_ly), float(p.price), len(p.bundle_items.all())]
        row += [1.0 if p.category_id == c else 0.0 for c in self.cat_ids]
        return row

    def training_set(self, until):
        """Rows whose target week is before `until`."""
        X, y, S = [], [], []
        start = self.first_week + timedelta(weeks=53)
        origin = start
        while origin + timedelta(weeks=1) < until:
            for h in range(1, MAX_H + 1):
                t = origin + timedelta(weeks=h)
                if t >= until:
                    break
                for p in self.products:
                    sc = self.scale(p, origin, h)
                    X.append(self.features(p, origin, h))
                    y.append(self.u(p.pk, t) / sc)
                    S.append(sc)
            origin += timedelta(weeks=1)
        return np.array(X), np.array(y, dtype=float)


def fit(X, y):
    models = {}
    for q in QUANTILES:
        m = GradientBoostingRegressor(loss="quantile", alpha=q, **GBR_PARAMS)
        m.fit(X, y)
        models[q] = m
    return models


def predict_period(models, data, p, origin, start, end):
    weeks = []
    w = start
    while w <= end:
        h = (w - origin).days // 7
        if h < 1:
            h = 1
        weeks.append((w, min(h, MAX_H)))
        w += timedelta(weeks=1)
    if not weeks:
        return [], np.array([]), np.array([]), np.array([])
    X = np.array([data.features(p, origin, h) for _, h in weeks])
    scales = np.array([data.scale(p, origin, h) for _, h in weeks])
    preds = {q: np.clip(models[q].predict(X), 0, None) * scales for q in QUANTILES}
    # keep quantiles ordered
    lo, mid, hi = preds[0.1], preds[0.5], preds[0.9]
    mid = np.maximum(mid, lo)
    hi = np.maximum(hi, mid)
    return [w for w, _ in weeks], lo, mid, hi


def backtest(data, today):
    start, end, intake = last_completed_period(today)
    origin = start - timedelta(weeks=1)
    X, y = data.training_set(until=start)
    if len(y) < 200:
        return {"note": "Not enough history for a back-test"}, []
    models = fit(X, y)
    results = []
    for p in data.products:
        weeks, lo, mid, hi = predict_period(models, data, p, origin, start, end)
        actual = sum(data.u(p.pk, w) for w in weeks)
        baseline = sum(data.u(p.pk, w - timedelta(weeks=52)) for w in weeks)
        results.append((p, float(np.sum(mid)), actual, baseline))
    # Calibrate the 80 % range for a period total from the back-test errors
    # (ratio actual / forecast, 10th and 90th percentiles).
    ratios = [a / f for _, f, a, _ in results if f >= 10]
    lo_f, hi_f = (float(np.percentile(ratios, 10)), float(np.percentile(ratios, 90))) if len(ratios) >= 8 else (0.6, 1.4)
    rows, err_model, err_base, inside = [], [], [], 0
    for p, f_mid, actual, baseline in results:
        f_lo, f_hi = f_mid * lo_f, f_mid * hi_f
        err_model.append(abs(f_mid - actual))
        err_base.append(abs(baseline - actual))
        ok = f_lo <= actual <= f_hi
        inside += ok
        rows.append({"product": p.name, "forecast": round(f_mid), "low": round(f_lo), "high": round(f_hi),
                     "actual": actual, "baseline": baseline, "error": round(f_mid - actual), "within": ok})
    n = len(results)
    rows.sort(key=lambda r: -r["actual"])
    actual_total = sum(r["actual"] for r in rows) or 1
    metrics = {
        "period": f"{start:%d %b %Y} – {end:%d %b %Y}",
        "mae": round(sum(err_model) / n, 1),
        "baseline_mae": round(sum(err_base) / n, 1),
        "wape": round(sum(err_model) / actual_total, 3),
        "baseline_wape": round(sum(err_base) / actual_total, 3),
        "baseline": "same weeks in the previous year",
        "range_low_factor": round(lo_f, 3),
        "range_high_factor": round(hi_f, 3),
        "range_coverage": round(inside / n, 2),
        "range_note": "80% range calibrated on this back-test, so coverage here is in-sample.",
        "products": n,
        "train_rows": int(len(y)),
    }
    return metrics, rows


@transaction.atomic
def train(version=None, today=None):
    today = today or timezone.localdate()
    data = Data()
    if data.first_week is None:
        return None
    metrics, rows = backtest(data, today)
    origin = monday(today)
    X, y = data.training_set(until=origin + timedelta(weeks=1))
    models = fit(X, y)
    start, end, intake = next_intake_period(today)
    ModelRun.objects.filter(kind=ModelRun.Kind.FORECAST).update(is_active=False)
    run = ModelRun.objects.create(
        kind=ModelRun.Kind.FORECAST,
        version=version or timezone.now().strftime("f%y%m%d.%H%M"),
        params={"model": "GradientBoostingRegressor (quantile loss)", "quantiles": list(QUANTILES), **{k: v for k, v in GBR_PARAMS.items()}},
        metrics={**metrics, "backtest": rows[:12]},
        data_summary={"weeks": len({w for d in data.units.values() for w in d}), "rows": int(len(y)),
                      "period_start": start.isoformat(), "period_end": end.isoformat(), "intake": intake.isoformat()},
    )
    for p in data.products:
        weeks, lo, mid, hi = predict_period(models, data, p, origin, start, end)
        total_hist = sum(data.units[p.pk].values())
        mid_f = float(np.sum(mid))
        lo_s = int(round(mid_f * metrics.get("range_low_factor", 0.6)))
        mid_s = int(round(mid_f))
        hi_s = int(round(mid_f * metrics.get("range_high_factor", 1.4)))
        # Confidence reflects how much comparable history the product has:
        # units sold in the same weeks last year.
        ly_units = sum(data.u(p.pk, w - timedelta(weeks=52)) for w in weeks)
        if total_hist < 60 or ly_units < 15:
            conf = "Low data"
        elif ly_units < 60:
            conf = "Medium"
        else:
            conf = "High"
        # chart series: last 26 weeks of history + all weeks up to the period end
        hist_weeks = [origin - timedelta(weeks=i) for i in range(25, -1, -1)]
        fw, flo, fmid, fhi = predict_period(models, data, p, origin, origin + timedelta(weeks=1), end)
        series = {
            "history": [[w.isoformat(), data.u(p.pk, w)] for w in hist_weeks],
            "forecast": [[w.isoformat(), round(float(a), 1), round(float(b), 1), round(float(c), 1)] for w, a, b, c in zip(fw, flo, fmid, fhi)],
            "last_year": [[w.isoformat(), data.u(p.pk, w - timedelta(weeks=52))] for w in fw],
        }
        ProductForecast.objects.create(run=run, product=p, period_start=start, period_end=end, low=lo_s, mid=mid_s,
                                       high=hi_s, confidence=conf, stock_at_run=p.stock, series=series)
    return run
