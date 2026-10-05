from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from safe_eth.eth.django.models import EthereumAddressBinaryField, Uint256Field

from chains.models import Chain

ZERO_ADDRESS = "0x" + "0" * 40
MIN_USD_PRICE = Decimal("0.00000001")
SPONSORING_FIELDS = (
    "sponsoring_daily_budget_wei",
    "sponsoring_per_safe_per_day",
    "sponsoring_per_owner_creations_per_day",
    "sponsoring_max_gas_limit",
)


def is_zero_address(value: object) -> bool:
    return value is not None and str(value).lower() == ZERO_ADDRESS


class RelayChain(models.Model):
    chain = models.OneToOneField(Chain, primary_key=True, on_delete=models.CASCADE)
    relayer_id = models.CharField(
        max_length=64,
        unique=True,
        validators=[RegexValidator(r"^[A-Za-z0-9_-]{1,64}\Z")],
        help_text="OpenZeppelin Relayer id of this chain's relayer, e.g. <em>base-sepolia</em> "
        "(letters, digits, - and _). "
        "A relayer of another network sends this chain's transactions to the wrong network.",
    )
    native_usd_price = models.DecimalField(
        max_digits=20,
        decimal_places=8,
        null=True,
        blank=True,
        validators=[MinValueValidator(MIN_USD_PRICE)],
        help_text="USD per 1 native coin. Empty = the gateway uses its price provider.",
    )
    refund_receiver = EthereumAddressBinaryField(
        null=True,
        blank=True,
        help_text="Treasury address (checksummed) that receives the Pay from Safe fee refunds. "
        "Must be an EOA (no contract code) if the native coin is a fee token: the Safe refunds "
        "the native coin with a 2300-gas send, which a contract such as a Safe cannot receive, "
        "so the transaction reverts with GS011. Token refunds work with any receiver.",
    )
    pay_from_safe_daily_budget_wei = Uint256Field(
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        help_text="Pay from Safe: gas the relayer may reserve per UTC day, in wei "
        "(1 ETH = 1000000000000000000). Empty = no budget.",
    )  # type: ignore[no-untyped-call]
    sponsoring_daily_budget_wei = Uint256Field(
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        help_text="Sponsoring: gas the relayer may reserve per UTC day, in wei "
        "(1 ETH = 1000000000000000000). Set all four sponsoring fields or none.",
    )  # type: ignore[no-untyped-call]
    sponsoring_per_safe_per_day = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        help_text="Sponsoring: relays per Safe account per UTC day.",
    )
    sponsoring_per_owner_creations_per_day = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Sponsoring: account creations per owner per UTC day. 0 = sponsored creation off.",
    )
    sponsoring_max_gas_limit = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        help_text="Sponsoring: maximum gas limit of one relayed transaction.",
    )

    def __str__(self) -> str:
        return f"Relay settings | chain_id={self.chain_id} | relayer={self.relayer_id}"

    def clean(self) -> None:
        errors: dict[str, str] = {}
        sponsoring_set = [getattr(self, field) is not None for field in SPONSORING_FIELDS]
        if any(sponsoring_set) and not all(sponsoring_set):
            message = "Set all four sponsoring fields or leave all four empty"
            errors.update({field: message for field in SPONSORING_FIELDS})
        if is_zero_address(self.refund_receiver):
            errors["refund_receiver"] = "The refund receiver cannot be the zero address"
        if errors:
            raise ValidationError(errors)


class RelayFeeToken(models.Model):
    relay_chain = models.ForeignKey(
        RelayChain, on_delete=models.CASCADE, related_name="tokens"
    )
    address = EthereumAddressBinaryField(
        help_text=f"Token contract address, checksummed. {ZERO_ADDRESS} = the chain's native coin; "
        "list it only when the refund receiver is an EOA."
    )
    symbol = models.CharField(max_length=32)
    decimals = models.PositiveSmallIntegerField()
    usd_price = models.DecimalField(
        max_digits=20,
        decimal_places=8,
        null=True,
        blank=True,
        validators=[MinValueValidator(MIN_USD_PRICE)],
        help_text="USD per 1 token. Empty = the gateway uses its price provider. "
        "Must be empty for the native coin.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["relay_chain", "address"], name="unique_relay_fee_token"
            )
        ]

    def __str__(self) -> str:
        return f"{self.symbol} | {self.address}"

    def clean(self) -> None:
        if not is_zero_address(self.address):
            return
        errors: dict[str, str] = {}
        if self.usd_price is not None:
            errors["usd_price"] = (
                "Leave empty for the native coin: its price is the native USD price above"
            )
        # The admin validates inline rows even when the parent has no chain yet
        relay_chain = getattr(self, "relay_chain", None)
        chain = getattr(relay_chain, "chain", None)
        if chain is not None and self.decimals != chain.currency_decimals:
            errors["decimals"] = (
                f"The native coin of this chain has {chain.currency_decimals} decimals"
            )
        if errors:
            raise ValidationError(errors)
