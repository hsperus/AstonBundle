from django.conf import settings

from catalog.models import Category


def site(request):
    from orders.basket import Basket

    ctx = {
        "nav_categories": Category.objects.all(),
        "basket_count": Basket(request).count if hasattr(request, "session") else 0,
        "free_delivery_threshold": settings.FREE_DELIVERY_THRESHOLD,
    }
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated and user.is_staff and request.path.startswith("/staff"):
        from catalog.models import Product
        from orders.models import ReturnRequest, ReturnStatus
        from support.models import Enquiry

        ctx["staff_counts"] = {
            "inventory": Product.objects.active().low_stock().count() + Product.objects.active().out_of_stock().count(),
            "returns": ReturnRequest.objects.filter(status=ReturnStatus.REQUESTED).count(),
            "enquiries": Enquiry.objects.filter(status=Enquiry.Status.UNREAD).count(),
        }
    return ctx
