from django.urls import path

from . import views

app_name = "core"
urlpatterns = [
    path("", views.home, name="home"),
    path("about/", views.about, name="about"),
    path("arrival-guide/", views.guide, name="guide"),
    path("help/<slug:slug>/", views.page, name="page"),
]
