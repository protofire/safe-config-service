
from django.contrib import admin
from django.db.models import Model
from django.http import HttpRequest

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

    def get_readonly_fields(
        self, request: HttpRequest, obj: RelayChain | None = None
    ) -> tuple[str, ...]:
        # chain is the primary key: changing it would copy the row, not move it
        return ("chain",) if obj else ()
