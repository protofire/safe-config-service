from typing import Any

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from chains.tests.factories import ChainFactory

from ..models import ZERO_ADDRESS, RelayChain, RelayFeeToken
from .factories import RelayChainFactory

USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"


def form_data(chain_id: str, tokens: list[dict[str, str]]) -> dict[str, Any]:
    data: dict[str, Any] = {
        "chain": chain_id,
        "relayer_id": "base-sepolia",
        "native_usd_price": "",
        "refund_receiver": "",
        "pay_from_safe_daily_budget_wei": "",
        "sponsoring_daily_budget_wei": "",
        "sponsoring_per_safe_per_day": "",
        "sponsoring_per_owner_creations_per_day": "",
        "sponsoring_max_gas_limit": "",
        "tokens-TOTAL_FORMS": str(len(tokens)),
        "tokens-INITIAL_FORMS": "0",
        "tokens-MIN_NUM_FORMS": "0",
        "tokens-MAX_NUM_FORMS": "1000",
    }
    for index, token in enumerate(tokens):
        for key, value in token.items():
            data[f"tokens-{index}-{key}"] = value
    return data


class RelayChainAdminTestCase(TestCase):
    def setUp(self) -> None:
        user = get_user_model().objects.create_superuser(
            username="admin", email="admin@example.com", password="password"
        )
        self.client.force_login(user)
        self.url = reverse("admin:relay_relaychain_add")

    def test_add_page_renders(self) -> None:
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

    def test_add_with_token_saves_both(self) -> None:
        chain = ChainFactory.create()
        token = {"address": USDC, "symbol": "USDC", "decimals": "6", "usd_price": "1"}

        response = self.client.post(self.url, form_data(str(chain.id), [token]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(RelayFeeToken.objects.get().address, USDC)

    def test_add_lowercase_address_is_rejected(self) -> None:
        chain = ChainFactory.create()
        token = {"address": USDC.lower(), "symbol": "USDC", "decimals": "6", "usd_price": "1"}

        response = self.client.post(self.url, form_data(str(chain.id), [token]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Enter a valid checksummed Ethereum Address.")
        self.assertEqual(RelayChain.objects.count(), 0)

    def test_add_without_chain_with_native_token_shows_errors(self) -> None:
        token = {"address": ZERO_ADDRESS, "symbol": "ETH", "decimals": "18", "usd_price": ""}

        response = self.client.post(self.url, form_data("", [token]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(RelayChain.objects.count(), 0)

    def test_add_same_token_twice_shows_error(self) -> None:
        chain = ChainFactory.create()
        token = {"address": USDC, "symbol": "USDC", "decimals": "6", "usd_price": "1"}
        tokens = [token, dict(token)]

        response = self.client.post(self.url, form_data(str(chain.id), tokens))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(RelayFeeToken.objects.count(), 0)

    def test_change_chain_on_edit_does_not_copy_the_row(self) -> None:
        # chain is the primary key: a new value would INSERT a second row
        relay_chain = RelayChainFactory.create()
        other_chain = ChainFactory.create()
        url = reverse("admin:relay_relaychain_change", args=[relay_chain.pk])

        response = self.client.post(url, form_data(str(other_chain.id), []))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            list(RelayChain.objects.values_list("pk", flat=True)), [relay_chain.pk]
        )
