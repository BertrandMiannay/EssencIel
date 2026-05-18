from django.urls import path
from . import views_front

urlpatterns = [
    path("", views_front.index, name="index"),
    path("carte/", views_front.carte, name="carte"),
    path("recherche/", views_front.recherche, name="recherche"),
]
