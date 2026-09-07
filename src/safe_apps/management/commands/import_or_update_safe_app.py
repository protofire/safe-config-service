import json
import logging
from collections import defaultdict
from io import BytesIO
import requests
from urllib.parse import urlparse

from django.core.files import File
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.forms import ValidationError

from safe_apps.models import SafeApp, Tag, Feature, Provider, Client, SocialProfile, validate_safe_app_icon_size

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Import safe apps from one or more remote URLs'

    def add_arguments(self, parser):
        parser.add_argument(
            '--remote-url',
            type=str,
            nargs='+',
            required=True,
            help='One or more URLs of JSON files containing safe app data. All sources are fetched and merged in a single run.'
        )
        parser.add_argument(
            '--chain-ids',
            type=str,
            default='',
            help='Comma-separated list of chain IDs'
        )

    def handle(self, *args, **options):
        remote_json_urls = options.get('remote_url')
        chain_ids_str = options.get('chain_ids')

        if not remote_json_urls:
            logger.error("The --remote-url argument is required but was not provided or is empty.")
            raise CommandError("The --remote-url argument is required but was not provided or is empty.")

        entries = []
        for remote_json_url in remote_json_urls:
            try:
                logger.info(f"Fetching safe app data from {remote_json_url}")
                response = requests.get(remote_json_url, timeout=10)
                response.raise_for_status()
                safe_apps_data = response.json()
            except requests.exceptions.RequestException as e:
                logger.error(f'Error fetching remote JSON from {remote_json_url}: {e}')
                continue
            except json.JSONDecodeError as e:
                logger.error(f'Error decoding JSON from {remote_json_url}: {e}')
                continue

            # Ensure safe_apps_data is a list, even if a single object is returned
            if not isinstance(safe_apps_data, list):
                safe_apps_data = [safe_apps_data]

            logger.info(f"Fetched {len(safe_apps_data)} safe apps from {remote_json_url}")
            entries.extend((remote_json_url, app_data) for app_data in safe_apps_data)

        if not entries:
            raise CommandError("No safe app data could be fetched from any of the provided --remote-url sources.")

        chain_ids = [int(chain_id) for chain_id in chain_ids_str.split(',') if chain_id.strip()] if chain_ids_str else []
        logger.info(f"Processing {len(entries)} safe apps from {len(remote_json_urls)} source(s) with chain IDs: {chain_ids}")
        self.import_safe_apps(entries, chain_ids)

    def import_safe_apps(self, entries, chain_ids):
        by_url = defaultdict(list)
        for source_url, app_data in entries:
            app_url = app_data.get('url')
            if not app_url or not app_data.get('name'):
                logger.warning(f"Skipping malformed safe app entry from {source_url} (missing 'url' or 'name'): {app_data!r}")
                continue
            by_url[app_url].append((source_url, app_data))

        imported_count = updated_count = skipped_count = 0

        with transaction.atomic():
            for app_url, sources in by_url.items():
                if len(sources) > 1:
                    conflicting_sources = ', '.join(source_url for source_url, _ in sources)
                    logger.warning(
                        f"Safe app with url={app_url} was found in multiple sources ({conflicting_sources}); "
                        f"skipping import for this app."
                    )
                    skipped_count += 1
                    continue

                _, app_data = sources[0]
                try:
                    with transaction.atomic():
                        created = self._process_safe_app(app_data, chain_ids)
                except Exception as e:
                    logger.error(f"Failed to import safe app url={app_url}: {e}")
                    skipped_count += 1
                    continue

                if created:
                    imported_count += 1
                else:
                    updated_count += 1

        logger.info(
            f"Imported {imported_count} new safe apps, updated {updated_count} existing safe apps, "
            f"skipped {skipped_count}"
        )

    def _process_safe_app(self, app_data: dict, chain_ids: list) -> bool:
        app_chain_ids = app_data.get('chainIds') or []
        app_chain_ids = [int(chain_id) for chain_id in app_chain_ids]
        if chain_ids:
            app_chain_ids = chain_ids

        # Additive, like tags/features/social profiles: an app imported once per network
        # (e.g. one curated JSON file per chain) must keep accumulating chain_ids across
        # runs rather than having each run's narrower list overwrite the previous one -
        # otherwise an app present on every chain (Transaction Builder, CSV Airdrop, ...)
        # would end up only ever showing the chain from the most recent import run.
        existing_app = SafeApp.objects.filter(url=app_data['url']).first()
        if existing_app:
            app_chain_ids = sorted(set(existing_app.chain_ids) | set(app_chain_ids))

        logger.info(f"Processing safe app: {app_data['name']} (URL: {app_data['url']}, Chain IDs: {app_chain_ids})")
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
        self._handle_social_profiles(safe_app, app_data)

        if created:
            logger.info(f"Imported new safe app: {safe_app.name}")
        else:
            logger.info(f"Updated existing safe app: {safe_app.name}")

        return created

    def _handle_icon_upload(self, safe_app: SafeApp, app_data: dict) -> None:
        if 'iconUrl' in app_data:
            try:
                full_image_url = app_data['iconUrl']
                logger.info(f"Downloading icon for safe app: {safe_app.name} (URL: {full_image_url})")
                response = requests.get(full_image_url, timeout=10)
                response.raise_for_status()
                icon_content = ContentFile(response.content)
                icon_name = f"{safe_app.app_id}.png"

                validate_safe_app_icon_size(icon_content)
                safe_app.icon_url.save(icon_name, icon_content, save=True)
                logger.info(f"Icon uploaded for safe app: {safe_app.name}")
            except requests.RequestException as e:
                logger.warning(f"Failed to download icon for {safe_app.name}: {str(e)}")
            except ValidationError as e:
                logger.warning(f"Skipping icon for {safe_app.name}: {str(e)}")
            except Exception as e:
                logger.warning(f"An unexpected error occurred while handling icon for {safe_app.name}: {str(e)}")

    def _handle_tags(self, safe_app: SafeApp, app_data: dict) -> None:
        tag_objects = []
        for tag_name in app_data.get('tags', []):
            logger.info(f"Processing tag: {tag_name} for safe app: {safe_app.name}")
            tag, _ = Tag.objects.get_or_create(name=tag_name)
            tag_objects.append(tag)
        # Additive: a tag missing from this payload is left in place rather than removed,
        # so a partial source can't wipe tags contributed by another one.
        if tag_objects:
            safe_app.tag_set.add(*tag_objects)

    def _handle_features(self, safe_app: SafeApp, app_data: dict) -> None:
        feature_objects = []
        for feature_key in app_data.get('features', []):
            logger.info(f"Processing feature: {feature_key} for safe app: {safe_app.name}")
            feature, _ = Feature.objects.get_or_create(key=feature_key)
            feature_objects.append(feature)
        # Additive, for the same reason as _handle_tags.
        if feature_objects:
            safe_app.feature_set.add(*feature_objects)

    def _handle_social_profiles(self, safe_app: SafeApp, app_data: dict) -> None:
        for profile_data in app_data.get('socialProfiles', []):
            platform = profile_data.get('platform')
            url = profile_data.get('url')
            if not platform or not url:
                logger.warning(f"Skipping malformed social profile for {safe_app.name}: {profile_data!r}")
                continue
            if platform not in SocialProfile.Platform.values:
                logger.warning(f"Skipping social profile with unknown platform '{platform}' for {safe_app.name}")
                continue

            logger.info(f"Processing social profile: {platform} for safe app: {safe_app.name}")
            # No DB uniqueness constraint on (safe_app, platform), so upsert manually by
            # first match instead of update_or_create to avoid creating duplicate rows.
            existing = SocialProfile.objects.filter(safe_app=safe_app, platform=platform).first()
            if existing:
                if existing.url != url:
                    existing.url = url
                    existing.save(update_fields=['url'])
            else:
                SocialProfile.objects.create(safe_app=safe_app, platform=platform, url=url)
