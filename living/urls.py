from django.urls import path

from . import views

app_name = "living"
urlpatterns = [
    path("", views.overview, name="overview"),
    path("rooms/<slug:slug>/", views.room, name="room"),
    path("request/", views.request_room, name="request"),
]
