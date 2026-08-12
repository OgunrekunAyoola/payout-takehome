from django.urls import include, path
from rest_framework.routers import DefaultRouter

from transfers.views import TransferViewSet

router = DefaultRouter()
router.register("transfers", TransferViewSet, basename="transfer")

urlpatterns = [
    path("api/", include(router.urls)),
]
