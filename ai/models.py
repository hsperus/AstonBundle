from django.db import models


class ModelRun(models.Model):
    """One training run of an AI model, with its evaluation results."""

    class Kind(models.TextChoices):
        RECOMMENDER = "recs", "Frequently bought together"
        FORECAST = "forecast", "Demand forecast"

    kind = models.CharField(max_length=10, choices=Kind.choices)
    version = models.CharField(max_length=20)
    trained_at = models.DateTimeField(auto_now_add=True)
    params = models.JSONField(default=dict)
    metrics = models.JSONField(default=dict)
    data_summary = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-trained_at"]

    def __str__(self):
        return f"{self.get_kind_display()} {self.version}"

    @classmethod
    def latest(cls, kind):
        return cls.objects.filter(kind=kind, is_active=True).order_by("-trained_at").first()


class ProductAssociation(models.Model):
    """Association rule  A → B  learned from past baskets."""

    run = models.ForeignKey(ModelRun, on_delete=models.CASCADE, related_name="associations")
    source = models.ForeignKey("catalog.Product", on_delete=models.CASCADE, related_name="+")
    target = models.ForeignKey("catalog.Product", on_delete=models.CASCADE, related_name="+")
    support = models.FloatField()
    confidence = models.FloatField()
    lift = models.FloatField()
    score = models.FloatField(db_index=True)

    class Meta:
        ordering = ["-score"]
        indexes = [models.Index(fields=["run", "source", "-score"])]


class ProductForecast(models.Model):
    run = models.ForeignKey(ModelRun, on_delete=models.CASCADE, related_name="forecasts")
    product = models.ForeignKey("catalog.Product", on_delete=models.CASCADE, related_name="forecasts")
    period_start = models.DateField()
    period_end = models.DateField()
    low = models.PositiveIntegerField(help_text="10th percentile of predicted units for the period")
    mid = models.PositiveIntegerField(help_text="Median prediction")
    high = models.PositiveIntegerField(help_text="90th percentile")
    confidence = models.CharField(max_length=10)  # High / Medium / Low data
    stock_at_run = models.IntegerField(default=0)
    on_order_at_run = models.IntegerField(default=0)
    series = models.JSONField(default=dict, help_text="Weekly history and forecast used for the chart")

    class Meta:
        ordering = ["-high"]
        unique_together = [("run", "product")]

    @property
    def suggested_reorder(self):
        """Top of the 80% range minus stock available now and stock already on order."""
        from inventory.models import PurchaseOrder

        on_order = sum(
            po.quantity for po in PurchaseOrder.objects.filter(product=self.product, status=PurchaseOrder.Status.OPEN)
        )
        return max(0, self.high - self.product.stock - on_order)
