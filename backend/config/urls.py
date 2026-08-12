from django.urls import include, path
from rest_framework.routers import SimpleRouter

from transfers.views import TransferViewSet

# SimpleRouter rather than DefaultRouter: the default additionally publishes an API-root
# index and `.json` format-suffix aliases for every route — unversioned public surface
# nothing here wants, and aliases that would bypass any future path-based rule written
# against the canonical paths.
router = SimpleRouter()
router.register("transfers", TransferViewSet, basename="transfer")

urlpatterns = [
    path("api/", include(router.urls)),
]
