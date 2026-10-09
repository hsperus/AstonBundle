from django.urls import path

from orders import views as order_views

from . import views

app_name = "accounts"
urlpatterns = [
    path("", views.overview, name="overview"),
    path("register/", views.register, name="register"),
    path("verify/", views.verify, name="verify"),
    path("demo-inbox/", views.demo_inbox, name="demo_inbox"),
    path("sign-in/", views.signin, name="signin"),
    path("sign-out/", views.signout, name="signout"),
    path("forgot-password/", views.forgot, name="forgot"),
    path("reset/<uidb64>/<token>/", views.ResetConfirm.as_view(), name="reset"),
    path("profile/", views.profile, name="profile"),
    path("orders/", order_views.order_list, name="orders"),
]
