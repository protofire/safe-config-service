import logging
from typing import Any

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from clients.safe_client_gateway import HookEvent, hook_event

from .models import RelayChain, RelayFeeToken

logger = logging.getLogger(__name__)


@receiver(post_save, sender=RelayChain)
@receiver(post_delete, sender=RelayChain)
def on_relay_chain_update(sender: RelayChain, instance: RelayChain, **kwargs: Any) -> None:
    logger.info("RelayChain update. Triggering CGW webhook")
    hook_event(HookEvent(type=HookEvent.Type.CHAIN_UPDATE, chain_id=instance.chain_id))


@receiver(post_save, sender=RelayFeeToken)
@receiver(post_delete, sender=RelayFeeToken)
def on_relay_fee_token_update(
    sender: RelayFeeToken, instance: RelayFeeToken, **kwargs: Any
) -> None:
    logger.info("RelayFeeToken update. Triggering CGW webhook")
    # relay_chain_id is the chain id (RelayChain's primary key); no query on a deleted parent
    hook_event(
        HookEvent(type=HookEvent.Type.CHAIN_UPDATE, chain_id=instance.relay_chain_id)
    )
