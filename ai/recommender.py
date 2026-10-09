"""'Frequently bought together' – item-to-item association rules learned from past
baskets (market-basket analysis).

For every pair of products A, B bought in the same order:
    support(A,B)    = P(A and B in a basket)
    confidence(A→B) = P(B | A)
    lift(A→B)       = confidence / P(B)     (>1 means bought together more than by chance)
Ranking score = confidence × sqrt(lift).

Only products a student chose individually are used (bundle contents are excluded,
otherwise the model would just re-learn our own bundle definitions).
Evaluation is a time-based hold-out: train on the oldest 80 % of orders, then for each
later basket with ≥2 items hide one item and check whether it appears in the top-3
suggestions for the rest of the basket (hit rate@3), compared with a "most popular" baseline.
"""
import math
import random
from collections import Counter, defaultdict
from itertools import permutations

from django.db import transaction
from django.utils import timezone

from catalog.models import Product
from orders.models import OrderLine, OrderStatus

from .models import ModelRun, ProductAssociation

MIN_PAIR_COUNT = 4
MAX_RULES_PER_ITEM = 8


def load_baskets():
    """[(created_at, frozenset(product_ids))] in time order."""
    rows = (
        OrderLine.objects.exclude(order__status=OrderStatus.CANCELLED)
        .filter(bundle__isnull=True, product__isnull=False)
        .values_list("order_id", "order__created_at", "product_id")
        .order_by("order__created_at")
    )
    baskets, when = defaultdict(set), {}
    for oid, created, pid in rows:
        baskets[oid].add(pid)
        when[oid] = created
    return [(when[o], frozenset(items)) for o, items in sorted(baskets.items(), key=lambda kv: when[kv[0]])]


def learn_rules(baskets):
    n = len(baskets)
    item_count, pair_count = Counter(), Counter()
    for items in baskets:
        item_count.update(items)
        if len(items) > 1:
            pair_count.update(permutations(items, 2))
    rules = defaultdict(list)
    for (a, b), c in pair_count.items():
        if c < MIN_PAIR_COUNT:
            continue
        conf = c / item_count[a]
        lift = conf / (item_count[b] / n)
        if lift <= 1.0:
            continue
        rules[a].append((b, c / n, conf, lift, conf * math.sqrt(lift)))
    for a in rules:
        rules[a].sort(key=lambda r: -r[4])
        rules[a] = rules[a][:MAX_RULES_PER_ITEM]
    popularity = [pid for pid, _ in item_count.most_common()]
    return rules, popularity


def recommend_from_rules(rules, popularity, query, k=3, exclude=(), allowed=None):
    scores = Counter()
    for a in query:
        for b, _s, _c, _l, score in rules.get(a, []):
            scores[b] += score
    banned = set(query) | set(exclude)
    ranked = [b for b, _ in scores.most_common() if b not in banned and (allowed is None or b in allowed)]
    if len(ranked) < k:  # fill with popular items so the box is never empty
        ranked += [p for p in popularity if p not in banned and p not in ranked and (allowed is None or p in allowed)]
    return ranked[:k]


def evaluate(baskets, k=3, seed=7):
    rng = random.Random(seed)
    split = int(len(baskets) * 0.8)
    train = [b for _, b in baskets[:split]]
    test = [b for _, b in baskets[split:] if len(b) >= 2]
    rules, popularity = learn_rules(train)
    hits_model = hits_pop = 0
    for items in test:
        items = list(items)
        hidden = rng.choice(items)
        query = [i for i in items if i != hidden]
        if hidden in recommend_from_rules(rules, popularity, query, k):
            hits_model += 1
        if hidden in [p for p in popularity if p not in query][:k]:
            hits_pop += 1
    n = max(1, len(test))
    return {
        "test_baskets": len(test),
        "train_baskets": len(train),
        "hit_rate_at_3": round(hits_model / n, 3),
        "baseline_hit_rate_at_3": round(hits_pop / n, 3),
        "split": "time-based 80/20",
    }


@transaction.atomic
def train(version=None):
    baskets = load_baskets()
    metrics = evaluate(baskets) if len(baskets) >= 50 else {"note": "Not enough baskets to evaluate"}
    rules, popularity = learn_rules([b for _, b in baskets])
    ModelRun.objects.filter(kind=ModelRun.Kind.RECOMMENDER).update(is_active=False)
    run = ModelRun.objects.create(
        kind=ModelRun.Kind.RECOMMENDER,
        version=version or timezone.now().strftime("r%y%m%d.%H%M"),
        params={"min_pair_count": MIN_PAIR_COUNT, "max_rules_per_item": MAX_RULES_PER_ITEM, "score": "confidence*sqrt(lift)"},
        metrics=metrics,
        data_summary={"baskets": len(baskets), "popular": popularity[:10],
                      "rules": sum(len(v) for v in rules.values())},
    )
    objs = [
        ProductAssociation(run=run, source_id=a, target_id=b, support=s, confidence=c, lift=l, score=sc)
        for a, lst in rules.items() for (b, s, c, l, sc) in lst
    ]
    ProductAssociation.objects.bulk_create(objs, batch_size=1000)
    return run


def recommend(product_ids, k=4, exclude=()):
    """Recommendations for the storefront. Out-of-stock and inactive items are never shown."""
    run = ModelRun.latest(ModelRun.Kind.RECOMMENDER)
    sellable = set(Product.objects.active().in_stock().values_list("pk", flat=True))
    if run is None:
        ids = list(Product.objects.active().in_stock().exclude(pk__in=list(product_ids) + list(exclude))
                   .order_by("-popularity").values_list("pk", flat=True)[:k])
    else:
        rules = defaultdict(list)
        for a, b, s, c, l, sc in run.associations.filter(source_id__in=product_ids).values_list(
                "source_id", "target_id", "support", "confidence", "lift", "score"):
            rules[a].append((b, s, c, l, sc))
        popularity = run.data_summary.get("popular", [])
        if not product_ids:
            ids = [p for p in popularity if p in sellable and p not in exclude][:k]
        else:
            ids = recommend_from_rules(rules, popularity, list(product_ids), k, exclude=exclude, allowed=sellable)
    products = {p.pk: p for p in Product.objects.filter(pk__in=ids)}
    return [products[i] for i in ids if i in products]
