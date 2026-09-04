import json
import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

import requests
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.forms import ValidationError

from chains.models import Chain, Feature, GasPrice, Wallet, validate_native_currency_size

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Import new chains from one or more remote URLs. Each source may be a flat JSON array of chains "
        "or a paginated (count/next/previous/results) /v1/chains/-shaped response; all pages and sources "
        "are fetched and merged in a single run. This command never modifies a chain that already exists "
        "locally: an existing chainId is always skipped, including its Features/GasPrice/Wallets."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--remote-url",
            type=str,
            nargs="+",
            required=True,
            help="One or more URLs to fetch chain data from.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        remote_json_urls: Optional[List[str]] = options.get("remote_url")

        if not remote_json_urls:
            logger.error("The --remote-url argument is required but was not provided or is empty.")
            raise CommandError("The --remote-url argument is required but was not provided or is empty.")

        entries: List[Tuple[str, Dict[str, Any]]] = []
        for remote_json_url in remote_json_urls:
            fetched = self._fetch_all_pages(remote_json_url)
            logger.info(f"Fetched {len(fetched)} chains from {remote_json_url}")
            entries.extend((remote_json_url, chain_data) for chain_data in fetched)

        if not entries:
            raise CommandError("No chain data could be fetched from any of the provided --remote-url sources.")

        logger.info(f"Processing {len(entries)} chains from {len(remote_json_urls)} source(s)")
        self.import_chains(entries)

    def _fetch_all_pages(self, remote_json_url: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        url: Optional[str] = remote_json_url
        visited = set()

        while url:
            if url in visited:
                logger.error(
                    f"Pagination loop detected while fetching {remote_json_url} (repeated {url}); stopping."
                )
                break
            visited.add(url)

            try:
                logger.info(f"Fetching chain data from {url}")
                response = requests.get(url, timeout=10)
                response.raise_for_status()
                data = response.json()
            except requests.exceptions.RequestException as e:
                logger.error(f"Error fetching remote JSON from {url}: {e}")
                break
            except json.JSONDecodeError as e:
                logger.error(f"Error decoding JSON from {url}: {e}")
                break

            if isinstance(data, list):
                results.extend(data)
                url = None
            elif isinstance(data, dict) and "results" in data:
                results.extend(data["results"])
                url = data.get("next")
            else:
                results.append(data)
                url = None

        return results

    def import_chains(self, entries: List[Tuple[str, Dict[str, Any]]]) -> None:
        by_chain_id: Dict[int, List[Tuple[str, Dict[str, Any]]]] = defaultdict(list)
        for source_url, chain_data in entries:
            raw_chain_id = chain_data.get("chainId")
            if raw_chain_id is None or not chain_data.get("chainName") or not chain_data.get("shortName"):
                logger.warning(
                    f"Skipping malformed chain entry from {source_url} "
                    f"(missing chainId/chainName/shortName): {chain_data!r}"
                )
                continue
            try:
                chain_id = int(raw_chain_id)
            except (TypeError, ValueError):
                logger.warning(f"Skipping chain entry from {source_url} with non-numeric chainId={raw_chain_id!r}")
                continue
            by_chain_id[chain_id].append((source_url, chain_data))

        imported_count = skipped_count = 0

        with transaction.atomic():
            for chain_id, sources in by_chain_id.items():
                if len(sources) > 1:
                    conflicting_sources = ", ".join(source_url for source_url, _ in sources)
                    logger.warning(
                        f"Chain with chainId={chain_id} was found in multiple sources ({conflicting_sources}); "
                        f"skipping import for this chain."
                    )
                    skipped_count += 1
                    continue

                if Chain.objects.filter(id=chain_id).exists():
                    logger.info(f"Chain chainId={chain_id} already exists locally; skipping (never overwritten).")
                    skipped_count += 1
                    continue

                _, chain_data = sources[0]
                try:
                    with transaction.atomic():
                        self._create_chain(chain_id, chain_data)
                except Exception as e:
                    logger.error(f"Failed to import chain chainId={chain_id}: {e}")
                    skipped_count += 1
                    continue

                imported_count += 1

        logger.info(f"Imported {imported_count} new chains, skipped {skipped_count}")

    def _create_chain(self, chain_id: int, chain_data: Dict[str, Any]) -> Chain:
        native_currency = chain_data.get("nativeCurrency") or {}
        rpc_uri = chain_data.get("rpcUri") or {}
        safe_apps_rpc_uri = chain_data.get("safeAppsRpcUri") or {}
        public_rpc_uri = chain_data.get("publicRpcUri") or {}
        block_explorer = chain_data.get("blockExplorerUriTemplate") or {}
        beacon_explorer = chain_data.get("beaconChainExplorerUriTemplate") or {}
        prices_provider = chain_data.get("pricesProvider") or {}
        balances_provider = chain_data.get("balancesProvider") or {}
        contract_addresses = chain_data.get("contractAddresses") or {}
        theme = chain_data.get("theme") or {}

        required: Dict[str, Any] = {
            "name": chain_data.get("chainName"),
            "short_name": chain_data.get("shortName"),
            "rpc_uri": rpc_uri.get("value"),
            "public_rpc_uri": public_rpc_uri.get("value"),
            "block_explorer_uri_address_template": block_explorer.get("address"),
            "block_explorer_uri_tx_hash_template": block_explorer.get("txHash"),
            "block_explorer_uri_api_template": block_explorer.get("api"),
            "currency_name": native_currency.get("name"),
            "currency_symbol": native_currency.get("symbol"),
            "transaction_service_uri": chain_data.get("transactionService"),
            "recommended_master_copy_version": chain_data.get("recommendedMasterCopyVersion"),
        }
        if chain_data.get("l2") is None:
            raise ValueError("missing required field: l2")
        missing = [field for field, value in required.items() if value in (None, "")]
        if missing:
            raise ValueError(f"missing required field(s): {', '.join(missing)}")

        logger.info(f"Creating new chain: {required['name']} (chainId: {chain_id})")

        # vpcTransactionService has no sensible default of its own; falling back to the
        # public transactionService keeps the (required, non-null) model field satisfied
        # when a source doesn't distinguish a separate VPC endpoint.
        vpc_transaction_service_uri = chain_data.get("vpcTransactionService") or required["transaction_service_uri"]

        chain = Chain.objects.create(
            id=chain_id,
            name=required["name"],
            short_name=required["short_name"],
            description=chain_data.get("description", ""),
            l2=bool(chain_data.get("l2")),
            is_testnet=bool(chain_data.get("isTestnet", False)),
            zk=bool(chain_data.get("zk", False)),
            rpc_authentication=rpc_uri.get("authentication", Chain.RpcAuthentication.NO_AUTHENTICATION),
            rpc_uri=required["rpc_uri"],
            safe_apps_rpc_authentication=safe_apps_rpc_uri.get(
                "authentication", Chain.RpcAuthentication.NO_AUTHENTICATION
            ),
            safe_apps_rpc_uri=safe_apps_rpc_uri.get("value", ""),
            public_rpc_authentication=public_rpc_uri.get(
                "authentication", Chain.RpcAuthentication.NO_AUTHENTICATION
            ),
            public_rpc_uri=required["public_rpc_uri"],
            block_explorer_uri_address_template=required["block_explorer_uri_address_template"],
            block_explorer_uri_tx_hash_template=required["block_explorer_uri_tx_hash_template"],
            block_explorer_uri_api_template=required["block_explorer_uri_api_template"],
            beacon_chain_explorer_uri_public_key_template=beacon_explorer.get("publicKey"),
            currency_name=required["currency_name"],
            currency_symbol=required["currency_symbol"],
            currency_decimals=native_currency.get("decimals", 18),
            transaction_service_uri=required["transaction_service_uri"],
            vpc_transaction_service_uri=vpc_transaction_service_uri,
            theme_text_color=theme.get("textColor", "#ffffff"),
            theme_background_color=theme.get("backgroundColor", "#000000"),
            ens_registry_address=chain_data.get("ensRegistryAddress"),
            recommended_master_copy_version=required["recommended_master_copy_version"],
            prices_provider_native_coin=prices_provider.get("nativeCoin"),
            prices_provider_chain_name=prices_provider.get("chainName"),
            balances_provider_chain_name=balances_provider.get("chainName"),
            balances_provider_enabled=bool(balances_provider.get("enabled", False)),
            safe_singleton_address=contract_addresses.get("safeSingletonAddress"),
            safe_proxy_factory_address=contract_addresses.get("safeProxyFactoryAddress"),
            multi_send_address=contract_addresses.get("multiSendAddress"),
            multi_send_call_only_address=contract_addresses.get("multiSendCallOnlyAddress"),
            fallback_handler_address=contract_addresses.get("fallbackHandlerAddress"),
            sign_message_lib_address=contract_addresses.get("signMessageLibAddress"),
            create_call_address=contract_addresses.get("createCallAddress"),
            simulate_tx_accessor_address=contract_addresses.get("simulateTxAccessorAddress"),
            safe_web_authn_signer_factory_address=contract_addresses.get("safeWebAuthnSignerFactoryAddress"),
        )

        self._handle_chain_logo(chain, chain_data.get("chainLogoUri"))
        self._handle_currency_logo(chain, native_currency.get("logoUri"))
        self._handle_gas_prices(chain, chain_data.get("gasPrice") or [])
        self._handle_features(chain, chain_data.get("features") or [])
        self._handle_wallets(chain, chain_data.get("disabledWallets") or [])

        logger.info(f"Imported new chain: {chain.name}")
        return chain

    def _handle_chain_logo(self, chain: Chain, logo_url: Optional[str]) -> None:
        if not logo_url:
            return
        try:
            logger.info(f"Downloading chain logo for {chain.name} (URL: {logo_url})")
            response = requests.get(logo_url, timeout=10)
            response.raise_for_status()
            image_content = ContentFile(response.content)
            validate_native_currency_size(image_content)
            chain.chain_logo_uri.save(f"{chain.id}_chain_logo.png", image_content, save=True)
        except requests.RequestException as e:
            logger.warning(f"Failed to download chain logo for {chain.name}: {e}")
        except ValidationError as e:
            logger.warning(f"Skipping chain logo for {chain.name}: {e}")
        except Exception as e:
            logger.warning(f"Unexpected error handling chain logo for {chain.name}: {e}")

    def _handle_currency_logo(self, chain: Chain, logo_url: Optional[str]) -> None:
        if not logo_url:
            return
        try:
            logger.info(f"Downloading currency logo for {chain.name} (URL: {logo_url})")
            response = requests.get(logo_url, timeout=10)
            response.raise_for_status()
            image_content = ContentFile(response.content)
            validate_native_currency_size(image_content)
            chain.currency_logo_uri.save(f"{chain.id}_currency_logo.png", image_content, save=True)
        except requests.RequestException as e:
            logger.warning(f"Failed to download currency logo for {chain.name}: {e}")
        except ValidationError as e:
            logger.warning(f"Skipping currency logo for {chain.name}: {e}")
        except Exception as e:
            logger.warning(f"Unexpected error handling currency logo for {chain.name}: {e}")

    def _handle_gas_prices(self, chain: Chain, gas_prices_data: List[Dict[str, Any]]) -> None:
        # Gas price entries are a ranked, unkeyed list (nothing identifies one entry across
        # runs), so - unlike tags/features - they're only ever written once here, for a
        # chain we just created; there's no existing state to merge with.
        for rank, entry in enumerate(gas_prices_data):
            gas_price_type = entry.get("type")
            if gas_price_type == "oracle":
                gas_price = GasPrice(
                    chain=chain,
                    oracle_uri=entry.get("uri"),
                    oracle_parameter=entry.get("gasParameter"),
                    gwei_factor=entry.get("gweiFactor", 1),
                    rank=rank,
                )
            elif gas_price_type == "fixed":
                gas_price = GasPrice(chain=chain, fixed_wei_value=entry.get("weiValue"), rank=rank)
            elif gas_price_type == "fixed1559":
                gas_price = GasPrice(
                    chain=chain,
                    max_fee_per_gas=entry.get("maxFeePerGas"),
                    max_priority_fee_per_gas=entry.get("maxPriorityFeePerGas"),
                    rank=rank,
                )
            else:
                logger.warning(f"Skipping gas price entry with unknown type '{gas_price_type}' for chain {chain.name}")
                continue

            gas_price.full_clean()
            gas_price.save()

    def _handle_features(self, chain: Chain, feature_keys: List[str]) -> None:
        feature_objects = []
        for feature_key in feature_keys:
            logger.info(f"Processing feature: {feature_key} for chain: {chain.name}")
            feature, _ = Feature.objects.get_or_create(key=feature_key)
            feature_objects.append(feature)
        if feature_objects:
            chain.feature_set.add(*feature_objects)

    def _handle_wallets(self, chain: Chain, disabled_wallet_keys: List[str]) -> None:
        disabled_keys = set(disabled_wallet_keys)

        for wallet_key in disabled_keys:
            logger.info(f"Processing disabled wallet: {wallet_key} for chain: {chain.name}")
            wallet, _ = Wallet.objects.get_or_create(key=wallet_key)
            wallet.chains.remove(chain)

        # Any wallet we already know about (from some other chain's disabledWallets list)
        # that this source didn't list as disabled for this chain is treated as enabled.
        # Note this can only ever *enable* wallets we already know about - a wallet key
        # that's enabled on every chain, and therefore never appears in any source's
        # disabledWallets list, can't be discovered through this endpoint shape at all.
        for wallet in Wallet.objects.exclude(key__in=disabled_keys):
            wallet.chains.add(chain)
