from django.urls import path

from . import views

app_name = "catalog"
urlpatterns = [
    path("shop/", views.all_products, name="all"),
    path("shop/search/", views.search, name="search"),
    path("shop/bundles/", views.bundles, name="bundles"),
    path("shop/bundles/<slug:slug>/", views.bundle, name="bundle"),
    path("shop/how-suggestions-work/", views.how_suggestions_work, name="how_suggestions_work"),
    path("shop/<slug:slug>/", views.category, name="category"),
    path("product/<slug:slug>/", views.product, name="product"),
]
