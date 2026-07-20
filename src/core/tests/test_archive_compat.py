"""S-803's archive-compatibility gate: upgrades never eat the archive.

Every CI run seeds a database at the BASELINE schema (core 0002, the first real
family schema) using the historical models from the migration graph, migrates
forward to the current head, and asserts the family survives: not just row
counts, but the semantic that matters most, the bridging household still seeing
both yards through the authorization guard. When a future migration breaks the
upgrade path from the v0.1-era schema, this fails the build before it can eat a
real family's archive (principle 8, T-UPGRADE-1).

The baseline is pinned and never advances casually: moving it forward is a
deliberate support-window decision recorded in the release notes, not a test
edit to make CI green.
"""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from core import scoping
from core.models import Member, Pod, PodMembership, Yard

BASELINE = [("core", "0002_pods_and_yards")]


@pytest.mark.django_db(transaction=True)
def test_baseline_archive_upgrades_to_head() -> None:
    executor = MigrationExecutor(connection)
    executor.migrate(BASELINE)

    # Seed with the models AS THEY WERE at the baseline, so this keeps working
    # no matter how current models drift from the 0002 schema.
    executor.loader.build_graph()
    old_apps = executor.loader.project_state(BASELINE).apps
    OldYard = old_apps.get_model("core", "Yard")
    OldPod = old_apps.get_model("core", "Pod")
    OldMember = old_apps.get_model("core", "Member")
    OldPodMembership = old_apps.get_model("core", "PodMembership")

    maternal = OldYard.objects.create(name="Maternal", slug="maternal")
    paternal = OldYard.objects.create(name="Paternal", slug="paternal")
    bridge = OldPod.objects.create(name="Bridge household")
    bridge.yards.set([maternal, paternal])
    maternal_pod = OldPod.objects.create(name="Maternal cousins")
    maternal_pod.yards.set([maternal])

    parent = OldMember.objects.create(display_name="Bridging parent", kinship_name="Dad")
    cousin = OldMember.objects.create(display_name="Maternal cousin")
    OldPodMembership.objects.create(member=parent, pod=bridge)
    OldPodMembership.objects.create(member=cousin, pod=maternal_pod)

    # The upgrade a real instance performs at boot.
    call_command("migrate", verbosity=0)

    # The archive survived: rows, relationships, and the isolation semantics.
    assert Yard.objects.count() == 2
    assert Pod.objects.count() == 2
    assert Member.objects.count() == 2
    upgraded_parent = Member.objects.get(display_name="Bridging parent")
    assert upgraded_parent.kinship_name == "Dad"
    assert PodMembership.objects.filter(member=upgraded_parent).count() == 1

    yard_ids = scoping.member_yard_ids(upgraded_parent)
    assert yard_ids == {
        Yard.objects.get(slug="maternal").id,
        Yard.objects.get(slug="paternal").id,
    }
    upgraded_cousin = Member.objects.get(display_name="Maternal cousin")
    assert scoping.member_yard_ids(upgraded_cousin) == {Yard.objects.get(slug="maternal").id}
