from django.urls import path

from relay.views import RelayChainView

app_name = "relay"

urlpatterns = [
    path("<int:pk>/", RelayChainView.as_view(), name="detail"),
]
