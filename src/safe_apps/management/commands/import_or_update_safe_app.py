import json
import logging
from io import BytesIO
import requests
from urllib.parse import urlparse

from django.core.files import File
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.forms import ValidationError

from safe_apps.models import SafeApp, Tag, Feature, Provider, Client, validate_safe_app_icon_size

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Import a safe app from a remote URL'

    def add_arguments(self, parser):
        parser.add_argument(
            '--remote-url',
            type=str,
            required=True,
            help='The URL of the JSON file containing the safe app data'
        )
        parser.add_argument(
            '--chain-ids',
            type=str,
            default='',
            help='Comma-separated list of chain IDs'
        )

    @transaction.atomic
    def handle(self, *args, **options):
        remote_json_url = options.get('remote_url')
        chain_ids_str = options.get('chain_ids')

        if not remote_json_url:
            raise CommandError("The --remote-url argument is required but was not provided or is empty.")

        try:
            response = requests.get(remote_json_url, timeout=10)
            response.raise_for_status()
            safe_apps_data = response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f'Error fetching remote JSON from {remote_json_url}: {e}')
            raise CommandError(f'Error fetching remote JSON: {e}')
        except json.JSONDecodeError as e:
            logger.error(f'Error decoding JSON from {remote_json_url}: {e}')
            raise CommandError(f'Error decoding JSON: {e}')
        except Exception as e:
            logger.error(f'Unexpected error: {e}')
            raise CommandError(f'Unexpected error: {e}')

        # Ensure safe_apps_data is a list, even if a single object is returned
        if not isinstance(safe_apps_data, list):
            safe_apps_data = [safe_apps_data]

        chain_ids = [int(chain_id) for chain_id in chain_ids_str.split(',') if chain_id.strip()] if chain_ids_str else []
        self.import_safe_apps(safe_apps_data, chain_ids)

    def import_safe_apps(self, safe_apps_data, chain_ids):
        imported_count = updated_count = 0

        with transaction.atomic():
            for app_data in safe_apps_data:
                app_chain_ids = app_data.get('chainIds') or []
                app_chain_ids = [int(chain_id) for chain_id in app_chain_ids]
                if chain_ids:
                    app_chain_ids = chain_ids

                safe_app, created = SafeApp.objects.update_or_create(
                    url=app_data['url'],
                    defaults={
                        'name': app_data['name'],
                        'description': app_data.get('description', ''),
                        'chain_ids': app_chain_ids,
                        'listed': True,
                    }
                )

                self._handle_icon_upload(safe_app, app_data)
                self._handle_tags(safe_app, app_data)
                self._handle_features(safe_app, app_data)

                safe_app.save()

                if created:
                    imported_count += 1
                else:
                    updated_count += 1

        self.stdout.write(self.style.SUCCESS(f"Imported {imported_count} new safe apps, updated {updated_count} existing safe apps"))

    def _handle_icon_upload(self, safe_app: SafeApp, app_data: dict) -> None:
        if 'iconUrl' in app_data:
            try:
                full_image_url = app_data['iconUrl']
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
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"An unexpected error occurred while handling icon for {safe_app.name}: {str(e)}"))

    def _handle_tags(self, safe_app: SafeApp, app_data: dict) -> None:
        tag_objects = []
        for tag_name in app_data.get('tags', []):
            tag, _ = Tag.objects.get_or_create(name=tag_name)
            tag_objects.append(tag)
        safe_app.tag_set.set(tag_objects)

    def _handle_features(self, safe_app: SafeApp, app_data: dict) -> None:
        feature_objects = []
        for feature_key in app_data.get('features', []):
            feature, _ = Feature.objects.get_or_create(key=feature_key)
            feature_objects.append(feature)
        safe_app.feature_set.set(feature_objects)
