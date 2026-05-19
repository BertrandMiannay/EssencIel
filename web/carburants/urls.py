from django.urls import path
from . import views

urlpatterns = [
    path("prix-moyen/", views.prix_moyen, name="prix-moyen"),
    path("top-prix/", views.top_prix, name="top-prix"),
    path("worst-prix/", views.worst_prix, name="worst-prix"),
    path("stations-proches/", views.stations_proches, name="stations-proches"),
]
