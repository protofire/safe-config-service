from django.contrib import admin
from django.db.models import Model

from .models import RelayChain, RelayFeeToken


class RelayFeeTokenInline(admin.TabularInline[Model, Model]):
    model = RelayFeeToken
    extra = 0
    verbose_name_plural = "Pay from Safe fee tokens"


@admin.register(RelayChain)
class RelayChainAdmin(admin.ModelAdmin[RelayChain]):
    list_display = ("chain", "relayer_id")
    search_fields = ("chain__id", "chain__name")
    inlines = [RelayFeeTokenInline]
