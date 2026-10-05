from decimal import Decimal

import factory
import web3
from factory.django import DjangoModelFactory

from chains.tests.factories import ChainFactory

from ..models import RelayChain, RelayFeeToken


class RelayChainFactory(DjangoModelFactory):  # type: ignore[misc]
    class Meta:
        model = RelayChain

    chain = factory.SubFactory(ChainFactory)
    relayer_id = factory.Sequence(lambda n: f"relayer-{n}")
    native_usd_price = Decimal("2500")
    refund_receiver = factory.LazyAttribute(lambda o: web3.Account.create().address)
    pay_from_safe_daily_budget_wei = 10**18
    sponsoring_daily_budget_wei = 10**17
    sponsoring_per_safe_per_day = 100
    sponsoring_per_owner_creations_per_day = 20
    sponsoring_max_gas_limit = 1_500_000


class RelayFeeTokenFactory(DjangoModelFactory):  # type: ignore[misc]
    class Meta:
        model = RelayFeeToken

    relay_chain = factory.SubFactory(RelayChainFactory)
    address = factory.LazyAttribute(lambda o: web3.Account.create().address)
    symbol = factory.Faker("cryptocurrency_code")
    decimals = 6
    usd_price = Decimal("1")
