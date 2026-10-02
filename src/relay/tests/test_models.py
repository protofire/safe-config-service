from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from chains.tests.factories import ChainFactory

from ..models import SPONSORING_FIELDS, ZERO_ADDRESS, RelayChain, RelayFeeToken
from .factories import RelayChainFactory, RelayFeeTokenFactory


class RelayChainCleanTestCase(TestCase):
    def test_complete_row_is_valid(self) -> None:
        relay_chain = RelayChainFactory.create()

        relay_chain.full_clean()

    def test_all_sponsoring_fields_empty_is_valid(self) -> None:
        relay_chain = RelayChainFactory.create(
            sponsoring_daily_budget_wei=None,
            sponsoring_per_safe_per_day=None,
            sponsoring_per_owner_creations_per_day=None,
            sponsoring_max_gas_limit=None,
        )

        relay_chain.full_clean()

    def test_partial_sponsoring_fields_are_rejected_on_all_four(self) -> None:
        relay_chain = RelayChainFactory.create(sponsoring_max_gas_limit=None)

        with self.assertRaises(ValidationError) as context:
            relay_chain.full_clean()

        self.assertEqual(
            set(context.exception.message_dict.keys()), set(SPONSORING_FIELDS)
        )

    def test_zero_creations_per_day_is_valid(self) -> None:
        relay_chain = RelayChainFactory.create(sponsoring_per_owner_creations_per_day=0)

        relay_chain.full_clean()

    def test_zero_address_refund_receiver_is_rejected(self) -> None:
        relay_chain = RelayChainFactory.create(refund_receiver=ZERO_ADDRESS)

        with self.assertRaises(ValidationError) as context:
            relay_chain.full_clean()

        self.assertIn("refund_receiver", context.exception.message_dict)

    def test_empty_refund_receiver_and_budget_are_valid(self) -> None:
        relay_chain = RelayChainFactory.create(
            refund_receiver=None, pay_from_safe_daily_budget_wei=None, native_usd_price=None
        )

        relay_chain.full_clean()

    def test_non_positive_values_are_rejected(self) -> None:
        cases = {
            "native_usd_price": Decimal("0"),
            "pay_from_safe_daily_budget_wei": 0,
            "sponsoring_daily_budget_wei": 0,
            "sponsoring_per_safe_per_day": 0,
            "sponsoring_max_gas_limit": 0,
        }
        for field, value in cases.items():
            with self.subTest(field=field):
                relay_chain = RelayChainFactory.build(
                    chain=ChainFactory.create(), **{field: value}
                )

                with self.assertRaises(ValidationError) as context:
                    relay_chain.full_clean()

                self.assertIn(field, context.exception.message_dict)

    def test_relayer_id_is_unique(self) -> None:
        RelayChainFactory.create(relayer_id="base-sepolia")
        duplicate = RelayChainFactory.build(
            chain=ChainFactory.create(), relayer_id="base-sepolia"
        )

        with self.assertRaises(ValidationError) as context:
            duplicate.full_clean()

        self.assertIn("relayer_id", context.exception.message_dict)

    def test_str(self) -> None:
        relay_chain = RelayChainFactory.create(relayer_id="base-sepolia")

        self.assertEqual(
            str(relay_chain),
            f"Relay settings | chain_id={relay_chain.chain_id} | relayer=base-sepolia",
        )


class RelayFeeTokenCleanTestCase(TestCase):
    def test_erc20_row_is_valid(self) -> None:
        token = RelayFeeTokenFactory.create()

        token.full_clean()

    def test_native_row_with_chain_decimals_and_no_price_is_valid(self) -> None:
        relay_chain = RelayChainFactory.create(chain=ChainFactory.create(currency_decimals=18))
        token = RelayFeeTokenFactory.create(
            relay_chain=relay_chain, address=ZERO_ADDRESS, symbol="ETH", decimals=18, usd_price=None
        )

        token.full_clean()

    def test_native_row_with_wrong_decimals_is_rejected(self) -> None:
        relay_chain = RelayChainFactory.create(chain=ChainFactory.create(currency_decimals=18))
        token = RelayFeeTokenFactory.create(
            relay_chain=relay_chain, address=ZERO_ADDRESS, symbol="ETH", decimals=6, usd_price=None
        )

        with self.assertRaises(ValidationError) as context:
            token.full_clean()

        self.assertIn("decimals", context.exception.message_dict)

    def test_native_row_with_usd_price_is_rejected(self) -> None:
        relay_chain = RelayChainFactory.create(chain=ChainFactory.create(currency_decimals=18))
        token = RelayFeeTokenFactory.create(
            relay_chain=relay_chain,
            address=ZERO_ADDRESS,
            symbol="ETH",
            decimals=18,
            usd_price=Decimal("2500"),
        )

        with self.assertRaises(ValidationError) as context:
            token.full_clean()

        self.assertIn("usd_price", context.exception.message_dict)

    def test_native_row_clean_without_chain_does_not_crash(self) -> None:
        # The admin validates inline rows even when the parent form has no chain yet
        token = RelayFeeToken(
            relay_chain=RelayChain(), address=ZERO_ADDRESS, symbol="ETH", decimals=18
        )

        token.clean()

    def test_zero_usd_price_is_rejected(self) -> None:
        token = RelayFeeTokenFactory.create(usd_price=Decimal("0"))

        with self.assertRaises(ValidationError) as context:
            token.full_clean()

        self.assertIn("usd_price", context.exception.message_dict)

    def test_same_address_in_other_case_is_a_duplicate(self) -> None:
        # full_clean() checksums via the field's to_python, then the constraint check finds the row
        token = RelayFeeTokenFactory.create()
        duplicate = RelayFeeTokenFactory.build(
            relay_chain=token.relay_chain, address=token.address.lower()
        )

        with self.assertRaises(ValidationError):
            duplicate.full_clean()

    def test_same_address_on_another_chain_is_valid(self) -> None:
        token = RelayFeeTokenFactory.create()
        other = RelayFeeTokenFactory.create(address=token.address)

        other.full_clean()
