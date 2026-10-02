from decimal import Decimal

from django.urls import reverse
from rest_framework.test import APITestCase

from chains.tests.factories import ChainFactory

from ..models import RelayChain
from .factories import RelayChainFactory, RelayFeeTokenFactory

# Verbatim copy of features/025-relay-settings/contract/relay-chain-84532.json (meta-repo)
CONTRACT = {
    "relayerId": "base-sepolia",
    "nativeUsdPrice": "2500.00000000",
    "refundReceiver": "0x798D0d04E1c52020d298b6246D9A87ceb4C08b36",
    "payFromSafeDailyBudgetWei": None,
    "sponsoringDailyBudgetWei": "100000000000000000",
    "sponsoringPerSafePerDay": 100,
    "sponsoringPerOwnerCreationsPerDay": 20,
    "sponsoringMaxGasLimit": 1500000,
    "tokens": [
        {
            "address": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
            "symbol": "USDC",
            "decimals": 6,
            "usdPrice": "1.00000000",
        }
    ],
}


def detail_url(chain_id: int) -> str:
    return reverse("v1:relay:detail", args=[chain_id])


class RelayChainContractViewTests(APITestCase):
    def test_contract_payload(self) -> None:
        relay_chain = RelayChainFactory.create(
            chain=ChainFactory.create(id=84532, currency_decimals=18),
            relayer_id="base-sepolia",
            native_usd_price=Decimal("2500"),
            # Lowercase on purpose: the API must return checksummed addresses
            refund_receiver="0x798d0d04e1c52020d298b6246d9a87ceb4c08b36",
            pay_from_safe_daily_budget_wei=None,
            sponsoring_daily_budget_wei=10**17,
            sponsoring_per_safe_per_day=100,
            sponsoring_per_owner_creations_per_day=20,
            sponsoring_max_gas_limit=1_500_000,
        )
        RelayFeeTokenFactory.create(
            relay_chain=relay_chain,
            address="0x036cbd53842c5426634e7929541ec2318f3dcf7e",
            symbol="USDC",
            decimals=6,
            usd_price=Decimal("1"),
        )

        response = self.client.get(detail_url(84532))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), CONTRACT)


class RelayChainViewTests(APITestCase):
    def test_404_without_relay_row(self) -> None:
        chain = ChainFactory.create()

        response = self.client.get(detail_url(chain.id))

        self.assertEqual(response.status_code, 404)

    def test_404_for_unknown_chain(self) -> None:
        response = self.client.get(detail_url(999_999_999))

        self.assertEqual(response.status_code, 404)

    def test_404_after_chain_deleted(self) -> None:
        relay_chain = RelayChainFactory.create()
        chain_id = relay_chain.chain_id
        relay_chain.chain.delete()

        response = self.client.get(detail_url(chain_id))

        self.assertEqual(response.status_code, 404)
        self.assertFalse(RelayChain.objects.filter(pk=chain_id).exists())

    def test_max_uint256_budget_is_exact_string(self) -> None:
        relay_chain = RelayChainFactory.create(pay_from_safe_daily_budget_wei=2**256 - 1)

        response = self.client.get(detail_url(relay_chain.chain_id))

        self.assertEqual(
            response.json()["payFromSafeDailyBudgetWei"], str(2**256 - 1)
        )

    def test_empty_optional_fields_are_null(self) -> None:
        relay_chain = RelayChainFactory.create(
            native_usd_price=None,
            refund_receiver=None,
            sponsoring_daily_budget_wei=None,
            sponsoring_per_safe_per_day=None,
            sponsoring_per_owner_creations_per_day=None,
            sponsoring_max_gas_limit=None,
        )

        body = self.client.get(detail_url(relay_chain.chain_id)).json()

        for key in (
            "nativeUsdPrice",
            "refundReceiver",
            "sponsoringDailyBudgetWei",
            "sponsoringPerSafePerDay",
            "sponsoringPerOwnerCreationsPerDay",
            "sponsoringMaxGasLimit",
        ):
            self.assertIsNone(body[key], key)
        self.assertEqual(body["tokens"], [])

    def test_tokens_ordered_by_symbol(self) -> None:
        relay_chain = RelayChainFactory.create()
        for symbol in ("USDT", "DAI", "USDC"):
            RelayFeeTokenFactory.create(relay_chain=relay_chain, symbol=symbol)

        body = self.client.get(detail_url(relay_chain.chain_id)).json()

        self.assertEqual([t["symbol"] for t in body["tokens"]], ["DAI", "USDC", "USDT"])

    def test_tokens_of_other_chains_are_not_listed(self) -> None:
        relay_chain = RelayChainFactory.create()
        RelayFeeTokenFactory.create(relay_chain=relay_chain, symbol="USDC")
        RelayFeeTokenFactory.create(symbol="DAI")

        body = self.client.get(detail_url(relay_chain.chain_id)).json()

        self.assertEqual([t["symbol"] for t in body["tokens"]], ["USDC"])
