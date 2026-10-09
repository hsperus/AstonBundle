from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils.text import slugify

TONES = [("", "Coral"), ("t", "Teal"), ("n", "Plum"), ("a", "Amber")]

# Icons available in the UI kit (CSS mask classes in astonbundle.css)
PRODUCT_ICONS = [
    "bed", "pillow", "towel", "hanger", "lamp", "cutlery", "pot", "plate", "kettle", "tub",
    "plug", "zap", "phone", "laptop", "headph", "calc", "book", "backpack", "usb", "umbrella",
    "shirt", "snow", "rain", "flask", "gift", "box", "pkg",
]


class Category(models.Model):
    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(max_length=60, unique=True)
    description = models.CharField(max_length=240, blank=True)
    icon = models.CharField(max_length=20, default="box")
    tone = models.CharField(max_length=2, choices=TONES, blank=True)
    sort = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort", "name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("catalog:category", args=[self.slug])


class ProductQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def in_stock(self):
        return self.filter(stock__gt=0)

    def low_stock(self):
        return self.filter(stock__gt=0, stock__lte=models.F("low_stock_threshold"))

    def out_of_stock(self):
        return self.filter(stock=0)


class Product(models.Model):
    sku = models.CharField("SKU", max_length=20, unique=True)
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    summary = models.CharField(max_length=200, help_text="One line shown on cards and search results.")
    description = models.TextField()
    features = models.TextField(blank=True, help_text="One bullet point per line.")
    specs = models.JSONField(default=list, blank=True, help_text='List of ["Label", "Value"] pairs.')
    price = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    stock = models.PositiveIntegerField(default=0, help_text="Units available to sell now.")
    low_stock_threshold = models.PositiveIntegerField(default=5)
    max_per_order = models.PositiveSmallIntegerField(default=10)
    icon = models.CharField(max_length=20, default="box", help_text="Placeholder illustration used when no photo is uploaded.")
    tone = models.CharField(max_length=2, choices=TONES, blank=True)
    image = models.ImageField(upload_to="products/", blank=True)
    image_alt = models.CharField("Image description (alt text)", max_length=200)
    returnable = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True, help_text="Inactive products are hidden from the shop.")
    rating_avg = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    rating_count = models.PositiveIntegerField(default=0)
    popularity = models.PositiveIntegerField(default=0, help_text="Units sold in the last 90 days (updated by orders).")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProductQuerySet.as_manager()

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(condition=Q(stock__gte=0), name="product_stock_not_negative"),
            models.CheckConstraint(condition=Q(price__gt=0), name="product_price_positive"),
        ]
        indexes = [models.Index(fields=["category", "is_active"]), models.Index(fields=["price"])]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)[:120] or "product"
            slug, n = base, 2
            while Product.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug, n = f"{base}-{n}", n + 1
            self.slug = slug
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("catalog:product", args=[self.slug])

    @property
    def stock_status(self):
        if self.stock <= 0:
            return "out"
        if self.stock <= self.low_stock_threshold:
            return "low"
        return "ok"

    @property
    def stock_label(self):
        s = self.stock_status
        if s == "out":
            return "Out of stock"
        if s == "low":
            return f"Only {self.stock} left"
        return "In stock"

    @property
    def order_limit(self):
        limit = self.max_per_order
        if self.stock_status == "low":
            limit = min(limit, 3)
        return max(0, min(limit, self.stock))

    @property
    def feature_list(self):
        return [f.strip() for f in self.features.splitlines() if f.strip()]

    @property
    def stars(self):
        r = round(float(self.rating_avg))
        return ["starf" if i <= r else "star" for i in range(1, 6)]


class Bundle(models.Model):
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True)
    tagline = models.CharField(max_length=120, help_text="e.g. 'sleep, wash, cook, charge'")
    description = models.TextField()
    price = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    icons = models.CharField(max_length=60, default="gift", help_text="Up to three icon names, comma separated.")
    tone = models.CharField(max_length=2, choices=TONES, blank=True)
    featured = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    sort = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort", "name"]
        constraints = [models.CheckConstraint(condition=Q(price__gt=0), name="bundle_price_positive")]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("catalog:bundle", args=[self.slug])

    @property
    def icon_list(self):
        return [i.strip() for i in self.icons.split(",") if i.strip()][:3]

    def lines(self):
        return list(self.items.select_related("product"))

    @property
    def photo_urls(self):
        """Up to four product photos, for the bundle collage."""
        return [i.product.image.url for i in self.items.all() if i.product.image][:4]

    @property
    def item_count(self):
        return sum(i.quantity for i in self.items.all())

    @property
    def separate_price(self):
        return sum((i.product.price * i.quantity for i in self.items.all()), Decimal("0"))

    @property
    def saving(self):
        return max(Decimal("0"), self.separate_price - self.price)

    @property
    def available(self):
        """How many complete bundles can be sold now."""
        items = list(self.items.select_related("product"))
        if not items:
            return 0
        return min(i.product.stock // i.quantity if i.product.is_active else 0 for i in items)

    def availability(self):
        """(status, label) for the bundle badge."""
        items = list(self.items.select_related("product"))
        out = [i for i in items if i.product.stock < i.quantity or not i.product.is_active]
        low = [i for i in items if i not in out and i.product.stock_status == "low"]
        if out:
            name = out[0].product.name.split(",")[0]
            label = f"{name} out of stock" if len(out) == 1 else f"{len(out)} items out of stock"
            return "out", label
        if low:
            return "low", f"{len(low)} item{'s' if len(low) > 1 else ''} low in stock"
        return "ok", "All items in stock"


class BundleItem(models.Model):
    bundle = models.ForeignKey(Bundle, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="bundle_items")
    quantity = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1)])

    class Meta:
        unique_together = [("bundle", "product")]

    def __str__(self):
        return f"{self.quantity} × {self.product}"
