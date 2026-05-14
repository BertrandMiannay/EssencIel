from django.urls import path, include

urlpatterns = [
    path("api/", include("carburants.urls")),
    path("", include("carburants.urls_front")),
]
