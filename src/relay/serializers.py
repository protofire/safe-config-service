from typing import Any

from drf_yasg.utils import swagger_serializer_method
from rest_framework import serializers
from rest_framework.utils.serializer_helpers import ReturnDict
from safe_eth.eth.django.serializers import EthereumAddressField

from .models import RelayChain, RelayFeeToken


class RelayFeeTokenSerializer(serializers.ModelSerializer[RelayFeeToken]):
    address = EthereumAddressField()

    class Meta:
        model = RelayFeeToken
        fields = ["address", "symbol", "decimals", "usd_price"]


class RelayChainSerializer(serializers.ModelSerializer[RelayChain]):
    refund_receiver = EthereumAddressField(allow_null=True)
    # Wei values exceed 2^53: strings, as chains/serializers.py does for gas prices
    pay_from_safe_daily_budget_wei = serializers.CharField(allow_null=True)
    sponsoring_daily_budget_wei = serializers.CharField(allow_null=True)
    tokens = serializers.SerializerMethodField()

    class Meta:
        model = RelayChain
        fields = [
            "relayer_id",
            "native_usd_price",
            "refund_receiver",
            "pay_from_safe_daily_budget_wei",
            "sponsoring_daily_budget_wei",
            "sponsoring_per_safe_per_day",
            "sponsoring_per_owner_creations_per_day",
            "sponsoring_max_gas_limit",
            "tokens",
        ]

    @swagger_serializer_method(serializer_or_field=RelayFeeTokenSerializer(many=True))  # type: ignore[untyped-decorator]
    def get_tokens(self, instance: RelayChain) -> ReturnDict[Any, Any]:
        # Sorted in Python so the prefetched rows are reused
        tokens = sorted(instance.tokens.all(), key=lambda token: token.symbol)
        return RelayFeeTokenSerializer(tokens, many=True).data
