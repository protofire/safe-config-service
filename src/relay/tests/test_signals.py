import responses
from django.test import TestCase, override_settings

from chains.tests.factories import ChainFactory

from .factories import RelayChainFactory, RelayFeeTokenFactory

HOOK_URL = "http://127.0.0.1/v1/hooks/events"


def hook_body(chain_id: int) -> bytes:
    return f'{{"type": "CHAIN_UPDATE", "chainId": "{chain_id}"}}'.encode("utf-8")


def bodies_since(start: int) -> list[bytes]:
    return [call.request.body for call in list(responses.calls)[start:]]


@override_settings(CGW_URL="http://127.0.0.1", CGW_AUTH_TOKEN="example-token")
class RelayHookTestCase(TestCase):
    @responses.activate
    def test_on_relay_chain_create(self) -> None:
        responses.add(responses.POST, HOOK_URL, status=200)
        chain = ChainFactory.create()  # sends its own hook first
        start = len(responses.calls)

        RelayChainFactory.create(chain=chain)

        self.assertEqual(bodies_since(start), [hook_body(chain.id)])
        self.assertEqual(
            responses.calls[start].request.headers.get("Authorization"),
            "Basic example-token",
        )

    @responses.activate
    def test_on_relay_chain_update(self) -> None:
        responses.add(responses.POST, HOOK_URL, status=200)
        relay_chain = RelayChainFactory.create()
        start = len(responses.calls)

        relay_chain.sponsoring_per_safe_per_day = 5
        relay_chain.save()

        self.assertEqual(bodies_since(start), [hook_body(relay_chain.chain_id)])

    @responses.activate
    def test_on_relay_chain_delete(self) -> None:
        responses.add(responses.POST, HOOK_URL, status=200)
        relay_chain = RelayChainFactory.create()
        chain_id = relay_chain.chain_id
        start = len(responses.calls)

        relay_chain.delete()

        self.assertEqual(bodies_since(start), [hook_body(chain_id)])

    @responses.activate
    def test_on_fee_token_create_and_delete(self) -> None:
        responses.add(responses.POST, HOOK_URL, status=200)
        relay_chain = RelayChainFactory.create()
        start = len(responses.calls)

        token = RelayFeeTokenFactory.create(relay_chain=relay_chain)
        token.delete()

        self.assertEqual(
            bodies_since(start),
            [hook_body(relay_chain.chain_id), hook_body(relay_chain.chain_id)],
        )
