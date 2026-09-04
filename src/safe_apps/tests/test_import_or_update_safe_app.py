from typing import Any, Dict

import responses
from django.core.management import call_command
from django.test import TestCase

from ..models import Feature, SafeApp, SocialProfile, Tag
from .factories import FeatureFactory, SafeAppFactory, TagFactory

SOURCE_A = "https://example.com/source-a.json"
SOURCE_B = "https://example.com/source-b.json"


def _app_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "url": "https://app.example.com",
        "name": "Example App",
        "description": "An example app",
        "chainIds": [1],
        "tags": [],
        "features": [],
        "socialProfiles": [],
    }
    payload.update(overrides)
    return payload


class ImportOrUpdateSafeAppCommandTests(TestCase):
    @responses.activate
    def test_creates_new_safe_app_from_single_source(self) -> None:
        responses.add(
            responses.GET,
            SOURCE_A,
            json=[
                _app_payload(
                    tags=["defi"],
                    features=["FEATURE_A"],
                    socialProfiles=[{"platform": "TWITTER", "url": "https://twitter.com/example"}],
                )
            ],
            status=200,
        )

        call_command("import_or_update_safe_app", "--remote-url", SOURCE_A)

        safe_app = SafeApp.objects.get(url="https://app.example.com")
        self.assertEqual(safe_app.name, "Example App")
        self.assertEqual(list(safe_app.chain_ids), [1])
        self.assertEqual({t.name for t in safe_app.tag_set.all()}, {"defi"})
        self.assertEqual({f.key for f in safe_app.feature_set.all()}, {"FEATURE_A"})
        self.assertEqual(
            list(SocialProfile.objects.filter(safe_app=safe_app).values_list("platform", "url")),
            [("TWITTER", "https://twitter.com/example")],
        )

    @responses.activate
    def test_merges_distinct_apps_from_multiple_sources_in_one_run(self) -> None:
        responses.add(
            responses.GET,
            SOURCE_A,
            json=[_app_payload(url="https://app-a.example.com", name="App A")],
            status=200,
        )
        responses.add(
            responses.GET,
            SOURCE_B,
            json=[_app_payload(url="https://app-b.example.com", name="App B")],
            status=200,
        )

        call_command("import_or_update_safe_app", "--remote-url", SOURCE_A, SOURCE_B)

        self.assertTrue(SafeApp.objects.filter(url="https://app-a.example.com").exists())
        self.assertTrue(SafeApp.objects.filter(url="https://app-b.example.com").exists())

    @responses.activate
    def test_skips_app_found_in_more_than_one_source(self) -> None:
        responses.add(
            responses.GET,
            SOURCE_A,
            json=[_app_payload(name="From A")],
            status=200,
        )
        responses.add(
            responses.GET,
            SOURCE_B,
            json=[_app_payload(name="From B")],
            status=200,
        )

        call_command("import_or_update_safe_app", "--remote-url", SOURCE_A, SOURCE_B)

        self.assertFalse(SafeApp.objects.filter(url="https://app.example.com").exists())

    @responses.activate
    def test_conflicting_app_does_not_block_unrelated_apps_in_other_sources(self) -> None:
        responses.add(
            responses.GET,
            SOURCE_A,
            json=[_app_payload(name="From A"), _app_payload(url="https://only-a.example.com", name="Only A")],
            status=200,
        )
        responses.add(
            responses.GET,
            SOURCE_B,
            json=[_app_payload(name="From B")],
            status=200,
        )

        call_command("import_or_update_safe_app", "--remote-url", SOURCE_A, SOURCE_B)

        self.assertFalse(SafeApp.objects.filter(url="https://app.example.com").exists())
        self.assertTrue(SafeApp.objects.filter(url="https://only-a.example.com").exists())

    @responses.activate
    def test_tags_and_features_are_additive_across_runs(self) -> None:
        safe_app = SafeAppFactory.create(url="https://app.example.com")
        TagFactory.create(name="existing-tag", safe_apps=(safe_app,))
        FeatureFactory.create(key="EXISTING_FEATURE", safe_apps=(safe_app,))

        responses.add(
            responses.GET,
            SOURCE_A,
            json=[_app_payload(tags=["new-tag"], features=["NEW_FEATURE"])],
            status=200,
        )

        call_command("import_or_update_safe_app", "--remote-url", SOURCE_A)

        safe_app.refresh_from_db()
        self.assertEqual(
            {t.name for t in safe_app.tag_set.all()}, {"existing-tag", "new-tag"}
        )
        self.assertEqual(
            {f.key for f in safe_app.feature_set.all()}, {"EXISTING_FEATURE", "NEW_FEATURE"}
        )
        # No duplicate Tag/Feature rows were created for names/keys that already existed.
        self.assertEqual(Tag.objects.filter(name="existing-tag").count(), 1)
        self.assertEqual(Feature.objects.filter(key="EXISTING_FEATURE").count(), 1)

    @responses.activate
    def test_social_profile_upsert_does_not_duplicate_or_drop_platforms(self) -> None:
        responses.add(
            responses.GET,
            SOURCE_A,
            json=[
                _app_payload(
                    socialProfiles=[{"platform": "TWITTER", "url": "https://twitter.com/old"}]
                )
            ],
            status=200,
        )
        call_command("import_or_update_safe_app", "--remote-url", SOURCE_A)
        responses.reset()

        # Second run: updates the Twitter URL and adds a Discord profile, without touching
        # any platform not mentioned in this payload... but Twitter IS mentioned here so it
        # should be updated in place rather than duplicated.
        responses.add(
            responses.GET,
            SOURCE_A,
            json=[
                _app_payload(
                    socialProfiles=[
                        {"platform": "TWITTER", "url": "https://twitter.com/new"},
                        {"platform": "DISCORD", "url": "https://discord.gg/example"},
                    ]
                )
            ],
            status=200,
        )
        call_command("import_or_update_safe_app", "--remote-url", SOURCE_A)

        safe_app = SafeApp.objects.get(url="https://app.example.com")
        profiles = {p.platform: p.url for p in SocialProfile.objects.filter(safe_app=safe_app)}
        self.assertEqual(
            profiles,
            {"TWITTER": "https://twitter.com/new", "DISCORD": "https://discord.gg/example"},
        )

    @responses.activate
    def test_malformed_entry_missing_url_is_skipped_without_aborting_run(self) -> None:
        responses.add(
            responses.GET,
            SOURCE_A,
            json=[
                {"name": "Missing url field", "chainIds": [1]},
                _app_payload(url="https://valid.example.com", name="Valid App"),
            ],
            status=200,
        )

        call_command("import_or_update_safe_app", "--remote-url", SOURCE_A)

        self.assertTrue(SafeApp.objects.filter(url="https://valid.example.com").exists())
        self.assertEqual(SafeApp.objects.count(), 1)

    @responses.activate
    def test_unreachable_source_does_not_block_other_sources(self) -> None:
        responses.add(responses.GET, SOURCE_A, status=500)
        responses.add(
            responses.GET,
            SOURCE_B,
            json=[_app_payload(url="https://only-b.example.com", name="Only B")],
            status=200,
        )

        call_command("import_or_update_safe_app", "--remote-url", SOURCE_A, SOURCE_B)

        self.assertTrue(SafeApp.objects.filter(url="https://only-b.example.com").exists())
