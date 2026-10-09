from django.urls import path

from . import views

app_name = "orders"
urlpatterns = [
    path("basket/", views.basket_view, name="basket"),
    path("basket/add/", views.basket_add, name="basket_add"),
    path("basket/add-many/", views.basket_add_many, name="basket_add_many"),
    path("checkout/", views.checkout_delivery, name="checkout_delivery"),
    path("checkout/review/", views.checkout_review, name="checkout_review"),
    path("checkout/payment/", views.checkout_payment, name="checkout_payment"),
    path("checkout/payment/authenticate/", views.checkout_authenticate, name="checkout_authenticate"),
    path("checkout/payment/apple-pay/", views.checkout_wallet, name="checkout_wallet"),
    path("checkout/done/<str:number>/", views.confirmation, name="confirmation"),
    path("account/orders/<str:number>/", views.order_detail, name="detail"),
    path("account/orders/<str:number>/cancel/", views.order_cancel, name="cancel"),
    path("account/orders/<str:number>/return/", views.return_request, name="return"),
    path("account/returns/<str:reference>/", views.return_done, name="return_done"),
]
