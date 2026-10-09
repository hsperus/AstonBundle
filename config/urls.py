from django.conf import settings
from django.urls import include, path, re_path
from django.views.static import serve

urlpatterns = [
    path("", include("core.urls")),
    path("", include("catalog.urls")),
    path("account/", include("accounts.urls")),
    path("", include("orders.urls")),
    path("", include("reviews.urls")),
    path("", include("support.urls")),
    path("staff/", include("staff.urls")),
]

# Product photos uploaded by staff are public. Return photos are NOT served here:
# they are only available to staff through staff:return_photo.
urlpatterns += [
    re_path(r"^media/products/(?P<path>[\w.\-/]+)$", serve, {"document_root": settings.MEDIA_ROOT / "products"}),
]

handler404 = "core.views.error_404"
handler500 = "core.views.error_500"
handler403 = "core.views.error_403"
