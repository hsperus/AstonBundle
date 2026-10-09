from django.urls import path

from . import views

app_name = "staff"
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("sign-in/", views.signin, name="signin"),
    path("sign-out/", views.signout, name="signout"),
    path("search/", views.search, name="search"),
    path("password/", views.password, name="password"),
    path("products/", views.products, name="products"),
    path("products/new/", views.product_edit, name="product_new"),
    path("products/<int:pk>/", views.product_edit, name="product_edit"),
    path("products/<int:pk>/delete/", views.product_delete, name="product_delete"),
    path("inventory/", views.inventory, name="inventory"),
    path("inventory/purchase-order/", views.create_po, name="create_po"),
    path("ai/", views.ai_insights, name="ai"),
    path("orders/", views.orders, name="orders"),
    path("customers/", views.customers, name="customers"),
    path("returns/", views.returns, name="returns"),
    path("returns/<int:pk>/photo/", views.return_photo, name="return_photo"),
    path("enquiries/", views.enquiries, name="enquiries"),
    path("access/", views.access, name="access"),
    path("invite/<str:token>/", views.accept_invite, name="accept_invite"),
]
