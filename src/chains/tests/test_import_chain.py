from typing import Any, Dict

import responses
from django.core.management import call_command
from django.test import TestCase

from ..models import Chain, Feature, GasPrice, Wallet
from .factories import ChainFactory, WalletFactory

SOURCE_A = "https://example.com/source-a.json"
SOURCE_B = "https://example.com/source-b.json"


def _chain_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "chainId": "1",
        "chainName": "Ethereum",
        "shortName": "eth",
        "description": "Ethereum Mainnet",
        "l2": False,
        "isTestnet": False,
        "zk": False,
        "rpcUri": {"authentication": "NO_AUTHENTICATION", "value": "https://rpc.example.com"},
        "safeAppsRpcUri": {"authentication": "NO_AUTHENTICATION", "value": "https://safe-rpc.example.com"},
        "publicRpcUri": {"authentication": "NO_AUTHENTICATION", "value": "https://public-rpc.example.com"},
        "blockExplorerUriTemplate": {
            "address": "https://explorer.example.com/address/{{address}}",
            "txHash": "https://explorer.example.com/tx/{{txHash}}",
            "api": "https://explorer.example.com/api",
        },
        "nativeCurrency": {"name": "Ether", "symbol": "ETH", "decimals": 18},
        "transactionService": "https://tx-service.example.com",
        "recommendedMasterCopyVersion": "1.3.0",
        "gasPrice": [],
        "features": [],
        "disabledWallets": [],
    }
    payload.update(overrides)
    return payload


class ImportChainCommandTests(TestCase):
    @responses.activate
    def test_creates_new_chain_from_single_source(self) -> None:
        responses.add(responses.GET, SOURCE_A, json=[_chain_payload()], status=200)

        call_command("import_chain", "--remote-url", SOURCE_A)

        chain = Chain.objects.get(id=1)
        self.assertEqual(chain.name, "Ethereum")
        self.assertEqual(chain.short_name, "eth")
        self.assertEqual(chain.rpc_uri, "https://rpc.example.com")
        self.assertEqual(chain.currency_name, "Ether")
        self.assertEqual(chain.currency_symbol, "ETH")
        self.assertEqual(chain.currency_decimals, 18)
        # No vpcTransactionService provided: falls back to the public transactionService.
        self.assertEqual(chain.vpc_transaction_service_uri, "https://tx-service.example.com")

    @responses.activate
    def test_existing_chain_is_never_overwritten(self) -> None:
        existing = ChainFactory.create(id=1, name="Existing Name", short_name="existing")
        responses.add(
            responses.GET,
            SOURCE_A,
            json=[_chain_payload(chainName="New Name", shortName="new-name")],
            status=200,
        )

        call_command("import_chain", "--remote-url", SOURCE_A)

        existing.refresh_from_db()
        self.assertEqual(existing.name, "Existing Name")
        self.assertEqual(existing.short_name, "existing")
        self.assertEqual(Chain.objects.count(), 1)

    @responses.activate
    def test_merges_distinct_chains_from_multiple_sources_in_one_run(self) -> None:
        responses.add(responses.GET, SOURCE_A, json=[_chain_payload(chainId="1", shortName="one")], status=200)
        responses.add(responses.GET, SOURCE_B, json=[_chain_payload(chainId="2", shortName="two")], status=200)

        call_command("import_chain", "--remote-url", SOURCE_A, SOURCE_B)

        self.assertTrue(Chain.objects.filter(id=1).exists())
        self.assertTrue(Chain.objects.filter(id=2).exists())

    @responses.activate
    def test_skips_chain_found_in_more_than_one_source(self) -> None:
        responses.add(responses.GET, SOURCE_A, json=[_chain_payload(chainName="From A")], status=200)
        responses.add(responses.GET, SOURCE_B, json=[_chain_payload(chainName="From B")], status=200)

        call_command("import_chain", "--remote-url", SOURCE_A, SOURCE_B)

        self.assertFalse(Chain.objects.filter(id=1).exists())

    @responses.activate
    def test_follows_pagination_across_all_pages(self) -> None:
        page_2_url = f"{SOURCE_A}?offset=1"
        responses.add(
            responses.GET,
            SOURCE_A,
            json={
                "count": 2,
                "next": page_2_url,
                "previous": None,
                "results": [_chain_payload(chainId="1", shortName="one")],
            },
            status=200,
        )
        responses.add(
            responses.GET,
            page_2_url,
            json={
                "count": 2,
                "next": None,
                "previous": SOURCE_A,
                "results": [_chain_payload(chainId="2", shortName="two")],
            },
            status=200,
        )

        call_command("import_chain", "--remote-url", SOURCE_A)

        self.assertTrue(Chain.objects.filter(id=1).exists())
        self.assertTrue(Chain.objects.filter(id=2).exists())

    @responses.activate
    def test_gas_price_variants_are_imported_in_rank_order(self) -> None:
        responses.add(
            responses.GET,
            SOURCE_A,
            json=[
                _chain_payload(
                    gasPrice=[
                        {"type": "oracle", "uri": "https://oracle.example.com", "gasParameter": "fast", "gweiFactor": "1.5"},
                        {"type": "fixed", "weiValue": "1000000000"},
                    ]
                )
            ],
            status=200,
        )

        call_command("import_chain", "--remote-url", SOURCE_A)

        gas_prices = list(GasPrice.objects.filter(chain_id=1).order_by("rank"))
        self.assertEqual(len(gas_prices), 2)
        self.assertEqual(gas_prices[0].oracle_uri, "https://oracle.example.com")
        self.assertEqual(gas_prices[0].oracle_parameter, "fast")
        self.assertEqual(gas_prices[0].rank, 0)
        self.assertEqual(gas_prices[1].fixed_wei_value, 1000000000)
        self.assertEqual(gas_prices[1].rank, 1)

    @responses.activate
    def test_features_are_created_and_linked(self) -> None:
        responses.add(responses.GET, SOURCE_A, json=[_chain_payload(features=["EIP1559"])], status=200)

        call_command("import_chain", "--remote-url", SOURCE_A)

        chain = Chain.objects.get(id=1)
        self.assertEqual({f.key for f in chain.feature_set.all()}, {"EIP1559"})
        self.assertTrue(Feature.objects.filter(key="EIP1559").exists())

    @responses.activate
    def test_only_default_wallets_are_auto_enabled(self) -> None:
        other_chain = ChainFactory.create(id=99)
        # A wallet outside the hardcoded default set: never auto-enabled, even if the
        # source doesn't disable it.
        unrelated_wallet = WalletFactory.create(key="ledger", chains=(other_chain,))

        responses.add(
            responses.GET,
            SOURCE_A,
            json=[_chain_payload(disabledWallets=["walletconnect_v2"])],
            status=200,
        )

        call_command("import_chain", "--remote-url", SOURCE_A)

        chain = Chain.objects.get(id=1)
        metamask = Wallet.objects.get(key="metamask")
        walletconnect = Wallet.objects.get(key="walletconnect_v2")
        unrelated_wallet.refresh_from_db()

        self.assertIn(chain, metamask.chains.all())
        self.assertNotIn(chain, walletconnect.chains.all())
        self.assertNotIn(chain, unrelated_wallet.chains.all())
        # Untouched: ledger's membership on the unrelated chain is preserved.
        self.assertIn(other_chain, unrelated_wallet.chains.all())

    @responses.activate
    def test_malformed_entry_missing_required_field_is_skipped(self) -> None:
        broken_payload = _chain_payload(chainId="2", shortName="broken")
        del broken_payload["rpcUri"]

        responses.add(
            responses.GET,
            SOURCE_A,
            json=[_chain_payload(chainId="1", shortName="ok"), broken_payload],
            status=200,
        )

        call_command("import_chain", "--remote-url", SOURCE_A)

        self.assertTrue(Chain.objects.filter(id=1).exists())
        self.assertFalse(Chain.objects.filter(id=2).exists())

    @responses.activate
    def test_unreachable_source_does_not_block_other_sources(self) -> None:
        responses.add(responses.GET, SOURCE_A, status=500)
        responses.add(responses.GET, SOURCE_B, json=[_chain_payload(chainId="2", shortName="two")], status=200)

        call_command("import_chain", "--remote-url", SOURCE_A, SOURCE_B)

        self.assertTrue(Chain.objects.filter(id=2).exists())
