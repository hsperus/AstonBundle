from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from catalog.models import Product
from orders.models import OrderLine, OrderStatus

from .forms import ReviewForm
from .models import Review

LABELS = {1: "Poor", 2: "Not great", 3: "OK", 4: "Good", 5: "Excellent"}


@login_required
def write(request, slug):
    product = get_object_or_404(Product, slug=slug)
    line = (OrderLine.objects.filter(order__user=request.user, order__status=OrderStatus.DELIVERED, product=product)
            .select_related("order").order_by("-order__created_at").first())
    if line is None:
        messages.error(request, "Only students who received this item can review it.")
        return redirect(product.get_absolute_url())
    if Review.objects.filter(product=product, user=request.user).exists():
        messages.info(request, "You have already reviewed this item. Thank you!")
        return redirect(product.get_absolute_url())
    form = ReviewForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        review = form.save(commit=False)
        review.product = product
        review.user = request.user
        review.verified_buyer = True
        review.save()
        messages.success(request, "Thank you! Your review is now on the product page.")
        return redirect(product.get_absolute_url() + "#reviews")
    return render(request, "reviews/write.html", {"p": product, "line": line, "form": form, "labels": LABELS})
