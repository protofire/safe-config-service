from typing import Any

from drf_yasg.utils import swagger_auto_schema
from rest_framework.generics import RetrieveAPIView
from rest_framework.request import Request
from rest_framework.response import Response

from .models import RelayChain
from .serializers import RelayChainSerializer


class RelayChainView(RetrieveAPIView):  # type: ignore[type-arg]
    serializer_class = RelayChainSerializer
    queryset = RelayChain.objects.prefetch_related("tokens")

    @swagger_auto_schema(
        operation_id="Get relay settings by chain id"
    )  # type: ignore[untyped-decorator]
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().get(request, *args, **kwargs)
