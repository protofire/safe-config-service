import json
import os
import re
from typing import Any, List
from urllib.request import urlopen
from urllib.parse import urljoin

from django.core.management.base import BaseCommand
from django.db import transaction
from django.core.files.base import ContentFile
from django.core.exceptions import ValidationError
#from dotenv import load_dotenv

from chains.models import Chain, Feature as ChainFeature, Wallet
from safe_apps.models import SafeApp, Tag, Feature as SafeAppFeature, validate_safe_app_icon_size
import requests

#load_dotenv()
config_url = os.getenv('CONFIG_URL', 'https://raw.githubusercontent.com/protofire/safe-configs/refs/heads/main/')

class Command(BaseCommand):
    help = "Import chains, features, wallets and safeApps"

    def load_json_data(self, file_path: str) -> dict:
        if file_path.startswith(('http://', 'https://')):
            with urlopen(file_path) as response:
                return json.loads(response.read())
        else:
            with open(file_path, 'r') as f:
                return json.load(f)

    def handle(self, *args: Any, **options: Any) -> None:
        is_url = config_url.startswith(('http://', 'https://'))
        join_path = urljoin if is_url else os.path.join

        files = {
            'features': join_path(config_url, 'configs/features.json'),
            'wallets': join_path(config_url, 'configs/wallets.json'),
            'safe_apps': join_path(config_url, 'configs/safeApps.json'),
            'chains': join_path(config_url, 'configs/chains.json'),
        }

        default_chain_ids_raw = os.getenv('DEFAULT_CHAIN_IDS', '')
        if default_chain_ids_raw.upper() == 'ALL':
            # Load all chain IDs from chains.json
            chains_data = self.load_json_data(files['chains'])
            default_chain_ids = [str(chain['chainId']) for chain in chains_data]
        else:
            default_chain_ids = [chain_id.strip() for chain_id in default_chain_ids_raw.split(',') if chain_id.strip()]

        print('Chains to import:', default_chain_ids)
        import_flags = {
            'features': os.getenv('IMPORT_FEATURES', '0').lower() == '1',
            'wallets': os.getenv('IMPORT_WALLETS', '0').lower() == '1',
            'safe_apps': os.getenv('IMPORT_SAFE_APPS', '0').lower() == '1',
            'chains': bool(default_chain_ids),
        }

        with transaction.atomic():
            for item, flag in import_flags.items():
                if flag:
                    method = getattr(self, f'import_{item}')
                    if item == 'safe_apps':
                        method(files[item], default_chain_ids)
                    elif item == 'chains':
                        method(files[item], default_chain_ids)
                    else:
                        method(files[item])

        self.stdout.write(self.style.SUCCESS("Import completed successfully"))

    def import_features(self, features_file: str, *args) -> None:
        try:
            features_data = self.load_json_data(features_file)
            existing_features = set(ChainFeature.objects.values_list('key', flat=True))
            new_features = [feature for feature in features_data if feature not in existing_features]
            
            ChainFeature.objects.bulk_create([ChainFeature(key=feature) for feature in new_features])
            
            self.stdout.write(self.style.SUCCESS(f"Imported {len(new_features)} new features"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error importing features: {str(e)}"))

    def import_wallets(self, wallets_file: str, *args) -> None:
        try:
            wallets_data = self.load_json_data(wallets_file)
            existing_wallets = set(Wallet.objects.values_list('key', flat=True))
            new_wallets = [wallet for wallet in wallets_data if wallet not in existing_wallets]
            
            Wallet.objects.bulk_create([Wallet(key=wallet) for wallet in new_wallets])
            
            self.stdout.write(self.style.SUCCESS(f"Imported {len(new_wallets)} new wallets"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error importing wallets: {str(e)}"))

    def import_safe_apps(self, safe_apps_file: str, default_chain_ids: List[str]) -> None:
        try:
            safe_apps_data = self.load_json_data(safe_apps_file)
            imported_count = updated_count = 0
            
            with transaction.atomic():
                for app_data in safe_apps_data:
                    chain_ids = app_data.get('chainIds') or default_chain_ids
                    chain_ids = [int(chain_id) for chain_id in chain_ids]

                    safe_app, created = SafeApp.objects.update_or_create(
                        url=app_data['url'],
                        defaults={
                            'name': app_data['name'],
                            'description': app_data.get('description', ''),
                            'chain_ids': chain_ids,
                            'listed': True,
                        }
                    )

                    self._handle_icon_upload(safe_app, app_data)
                    self._handle_tags(safe_app, app_data)
                    self._handle_features(safe_app, app_data)

                    if created:
                        imported_count += 1
                    else:
                        updated_count += 1
            
            self.stdout.write(self.style.SUCCESS(f"Imported {imported_count} new safe apps, updated {updated_count} existing safe apps"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error importing safe apps: {str(e)}"))

    def _handle_icon_upload(self, safe_app: SafeApp, app_data: dict) -> None:
        if 'iconUrl' in app_data:
            try:
                full_image_url = f"{config_url}{app_data['iconUrl']}"
                response = requests.get(full_image_url, timeout=10)
                response.raise_for_status()
                icon_content = ContentFile(response.content)
                icon_name = f"{safe_app.app_id}.png"
                
                validate_safe_app_icon_size(icon_content)
                safe_app.icon_url.save(icon_name, icon_content, save=True)
            except requests.RequestException as e:
                self.stdout.write(self.style.WARNING(f"Failed to download icon for {safe_app.name}: {str(e)}"))
            except ValidationError as e:
                self.stdout.write(self.style.WARNING(f"Skipping icon for {safe_app.name}: {str(e)}"))

    def _handle_tags(self, safe_app: SafeApp, app_data: dict) -> None:
        tag_objects = []
        for tag_name in app_data.get('tags', []):
            tag, _ = Tag.objects.get_or_create(name=tag_name)
            tag_objects.append(tag)
        safe_app.tag_set.set(tag_objects)

    def _handle_features(self, safe_app: SafeApp, app_data: dict) -> None:
        feature_objects = []
        for feature_key in app_data.get('features', []):
            feature, _ = SafeAppFeature.objects.get_or_create(key=feature_key)
            feature_objects.append(feature)
        safe_app.feature_set.set(feature_objects)

    def import_chains(self, chains_file: str, default_chain_ids: List[str]) -> None:
        try:
            chains_data = self.load_json_data(chains_file)
            chains_to_import = [chain for chain in chains_data if str(chain["chainId"]) in default_chain_ids]

            if not chains_to_import:
                self.stdout.write(self.style.WARNING("No chains found with the provided chain IDs"))
                return

            default_wallets = ["metamask", "ledger", "trezor", "walletConnect_v2"]
            default_features = [
                "EIP1271", "COUNTERFACTUAL", "DELETE_TX", "SAFE_141",
                "SAFE_APPS", "SAFE_TX_GAS_OPTIONAL", "SPEED_UP_TX"
            ]

            for chain_data in chains_to_import:
                chain_id = int(chain_data["chainId"])
                chain_defaults = self._prepare_chain_defaults(chain_data)

                chain, created = Chain.objects.update_or_create(id=chain_id, defaults=chain_defaults)

                self._handle_chain_logo_upload(chain, chain_data)
                self._handle_currency_logo_upload(chain, chain_data)

                # Add default wallets
                for wallet_key in default_wallets:
                    wallet, _ = Wallet.objects.get_or_create(key=wallet_key)
                    chain.wallet_set.add(wallet)

                # Add features
                features_to_add = chain_data.get("features", default_features)
                for feature_key in features_to_add:
                    feature, _ = ChainFeature.objects.get_or_create(key=feature_key)
                    chain.feature_set.add(feature)

                action = "Created" if created else "Updated"
                self.stdout.write(self.style.SUCCESS(f"{action} chain: {chain.name} (ID: {chain.id})"))

            self.stdout.write(self.style.SUCCESS("Chain import completed successfully"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error importing chains: {str(e)}"))

    def _prepare_chain_defaults(self, chain_data: dict) -> dict:
        if "blockExplorerUriTemplate" in chain_data:
            block_explorer_uri_address_template = chain_data["blockExplorerUriTemplate"]["address"]
            block_explorer_uri_tx_hash_template = chain_data["blockExplorerUriTemplate"]["txHash"]
            block_explorer_uri_api_template = chain_data["blockExplorerUriTemplate"]["api"]
        elif "blockExplorerUri" in chain_data:
            block_explorer = chain_data.get("blockExplorerUri", "").rstrip("/")
            block_explorer_uri_address_template = f"{block_explorer}/address/{{{{address}}}}"
            block_explorer_uri_tx_hash_template = f"{block_explorer}/tx/{{{{txHash}}}}"
            block_explorer_uri_api_template = f"{re.sub(r'^https?://', 'https://api.', block_explorer)}/api?module={{module}}&action={{action}}&address={{address}}&apiKey={{apiKey}}"
        else:
            self.stdout.write(self.style.WARNING("No block explorer found for chain"))
            return
        return {
            "name": chain_data["chainName"],
            "description": chain_data.get("description", ""),
            "l2": chain_data.get("l2", False),
            "is_testnet": chain_data.get("isTestnet", False),
            "rpc_uri": chain_data.get("rpcUri", {}).get("value") or chain_data["rpcUri"],
            "rpc_authentication": Chain.RpcAuthentication[chain_data.get("rpcUri", {}).get("authentication", "NO_AUTHENTICATION")],
            "safe_apps_rpc_uri": chain_data.get("safeAppsRpcUri", {}).get("value") or chain_data["rpcUri"],
            "safe_apps_rpc_authentication": Chain.RpcAuthentication[chain_data.get("safeAppsRpcUri", {}).get("authentication", "NO_AUTHENTICATION")],
            "public_rpc_uri": chain_data.get("publicRpcUri", {}).get("value") or chain_data["rpcUri"],
            "public_rpc_authentication": Chain.RpcAuthentication[chain_data.get("publicRpcUri", {}).get("authentication", "NO_AUTHENTICATION")],
            "transaction_service_uri": chain_data["transactionService"],
            "vpc_transaction_service_uri": chain_data["transactionService"],
            "block_explorer_uri_address_template": block_explorer_uri_address_template,
            "block_explorer_uri_tx_hash_template": block_explorer_uri_tx_hash_template,
            "block_explorer_uri_api_template": block_explorer_uri_api_template,
            "currency_name": chain_data["nativeCurrency"]["name"],
            "currency_symbol": chain_data["nativeCurrency"]["symbol"],
            "currency_decimals": chain_data["nativeCurrency"]["decimals"],
            "ens_registry_address": chain_data.get("ensRegistryAddress", None),
            "recommended_master_copy_version": chain_data.get("recommendedMasterCopyVersion", "1.3.0"),
            "theme_text_color": chain_data.get("theme", {}).get("textColor", "#ffffff"),
            "theme_background_color": chain_data.get("theme", {}).get("backgroundColor", "#000000"),
            "short_name": chain_data.get("shortName", ""),
        }

    def _handle_chain_logo_upload(self, chain: Chain, chain_data: dict) -> None:
        if "chainLogoUri" in chain_data:
            self._upload_image(chain, "chain_logo_uri", chain_data["chainLogoUri"], f"chain_logo_{chain.id}.png")

    def _handle_currency_logo_upload(self, chain: Chain, chain_data: dict) -> None:
        if "logoUri" in chain_data["nativeCurrency"]:
            self._upload_image(chain, "currency_logo_uri", chain_data["nativeCurrency"]["logoUri"], f"currency_logo_{chain.id}.png")

    def _upload_image(self, obj: Any, field_name: str, image_url: str, file_name: str) -> None:
        full_image_url = f"{config_url}{image_url}"
        response = requests.get(full_image_url)
        if response.status_code == 200:
            content = ContentFile(response.content)
            getattr(obj, field_name).save(file_name, content, save=True)