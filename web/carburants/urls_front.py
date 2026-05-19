from django.urls import path
from . import views_front

urlpatterns = [
    path("", views_front.index, name="index"),
    path("trouver/", views_front.trouver, name="trouver"),
    path("evolution/", views_front.evolution, name="evolution"),
]
