from drf_yasg.utils import swagger_serializer_method
from rest_framework import serializers

from .models import Chain


class ThemeSerializer(serializers.Serializer):
    text_color = serializers.CharField(source="theme_text_color")
    background_color = serializers.CharField(source="theme_background_color")


class CurrencySerializer(serializers.Serializer):
    name = serializers.CharField(source="currency_name")
    symbol = serializers.CharField(source="currency_symbol")
    decimals = serializers.IntegerField(source="currency_decimals")


class ChainSerializer(serializers.ModelSerializer):
    chain_id = serializers.CharField(source="id")
    chain_name = serializers.CharField(source="name")
    native_currency = serializers.SerializerMethodField()
    transaction_service = serializers.URLField(
        source="transaction_service_url", default=None
    )
    theme = serializers.SerializerMethodField()

    class Meta:
        model = Chain
        fields = [
            "chain_id",
            "chain_name",
            "rpc_url",
            "block_explorer_url",
            "native_currency",
            "transaction_service",
            "theme",
        ]

    @staticmethod
    @swagger_serializer_method(serializer_or_field=CurrencySerializer)
    def get_native_currency(obj):
        return CurrencySerializer(obj).data

    @staticmethod
    @swagger_serializer_method(serializer_or_field=ThemeSerializer)
    def get_theme(obj):
        return ThemeSerializer(obj).data