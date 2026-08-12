from django.urls import include, path
from rest_framework.routers import SimpleRouter

from transfers.views import TransferViewSet
from transfers.webhooks.views import ProviderWebhookView

# SimpleRouter rather than DefaultRouter: the default additionally publishes an API-root
# index and `.json` format-suffix aliases for every route — unversioned public surface
# nothing here wants, and aliases that would bypass any future path-based rule written
# against the canonical paths.
router = SimpleRouter()
router.register("transfers", TransferViewSet, basename="transfer")

urlpatterns = [
    path("api/", include(router.urls)),
    path(
        "api/webhooks/provider/",
        ProviderWebhookView.as_view(),
        name="provider-webhook",
    ),
]
