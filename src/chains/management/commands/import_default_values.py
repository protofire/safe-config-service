import logging

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from chains.models import Wallet, Feature

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Import wallets and feature flags into the database'

    def add_arguments(self, parser):
        parser.add_argument(
            '--wallets',
            type=str,
            help='Comma-separated list of wallet keys to import',
        )
        parser.add_argument(
            '--feature-flags',
            type=str,
            help='Comma-separated list of feature flag keys to import',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        wallets_string = options.get('wallets')
        feature_flags_string = options.get('feature-flags')

        # Import wallets
        if wallets_string:
            wallets_to_import = [wallet.strip() for wallet in wallets_string.split(',') if wallet.strip()]
            self.import_wallets(wallets_to_import)

        # Import feature flags
        if feature_flags_string:
            feature_flags_to_import = [flag.strip() for flag in feature_flags_string.split(',') if flag.strip()]
            self.import_feature_flags(feature_flags_to_import)

    def import_wallets(self, wallets_to_import):
        if not wallets_to_import:
            logger.error('No valid wallet keys found in the provided string.')
            raise CommandError('No valid wallet keys found in the provided string.')

        created_count = 0
        skipped_count = 0

        for wallet_key in wallets_to_import:
            # Check if wallet already exists, create if not
            wallet, created = Wallet.objects.get_or_create(key=wallet_key)
            if created:
                logger.info(f'Created wallet: "{wallet_key}"')
                created_count += 1
            else:
                logger.warning(f'Wallet "{wallet_key}" already exists, skipping')
                skipped_count += 1

        logger.info(
            f'Wallet import complete: {created_count} created, {skipped_count} skipped'
        )

    def import_feature_flags(self, feature_flags_to_import):
        if not feature_flags_to_import:
            logger.error('No valid feature flag keys found in the provided string.')
            raise CommandError('No valid feature flag keys found in the provided string.')

        created_count = 0
        skipped_count = 0

        for feature_flag in feature_flags_to_import:
            # Check if feature flag already exists, create if not
            feature, created = Feature.objects.get_or_create(key=feature_flag, defaults={'description': ''})
            if created:
                logger.info(f'Created feature flag: "{feature_flag}"')
                created_count += 1
            else:
                logger.warning(f'Feature flag "{feature_flag}" already exists, skipping')
                skipped_count += 1

        logger.info(
            f'Feature flag import complete: {created_count} created, {skipped_count} skipped'
        )