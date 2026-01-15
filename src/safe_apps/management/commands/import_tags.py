import logging

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from safe_apps.models import Tag

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Import tags for safe apps'

    def add_arguments(self, parser):
        parser.add_argument(
            '--tags',
            type=str,
            help='Comma-separated list of tag names to import',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        tags_string = options.get('tags')

        if not tags_string:
            logger.error('No tags provided. Use --tags argument.')
            raise CommandError('No tags provided. Use --tags argument.')

        tags_to_import = [tag.strip() for tag in tags_string.split(',') if tag.strip()]

        if not tags_to_import:
            logger.error('No valid tags found in the provided string.')
            raise CommandError('No valid tags found in the provided string.')

        created_count = 0
        skipped_count = 0

        for tag_name in tags_to_import:
            # Check if tag already exists
            tag, created = Tag.objects.get_or_create(name=tag_name)
            if created:
                logger.info(f'Created tag: "{tag_name}"')
                created_count += 1
            else:
                logger.warning(f'Tag "{tag_name}" already exists, skipping')
                skipped_count += 1

        logger.info(
            f'Import complete: {created_count} tags created, {skipped_count} skipped'
        )