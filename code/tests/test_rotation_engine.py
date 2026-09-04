"""
Tests for the rotation engine — the critical file.

Covers Orbit's core promises:
  * group sizing (6..8),
  * keep ~50% of a prior group (continuity),
  * swap ~50% for haven't-met members (anti-clique / novelty),
  * hard block constraint (safety),
  * fair owner assignment (never last cycle's owner),
  * determinism (same seed -> same proposal),
  * no mutation of inputs (engine purity).
"""
import unittest

from orbit.matching.rotation_engine import (
    IDEAL_SIZE,
    TARGET_MAX,
    TARGET_MIN,
    MemberSnapshot,
    RotationEngine,
    RotationInput,
)


def make_members(n, area="default", availability=("tue_pm",), reliability=100):
    """Helper: build n snapshots m0..m{n-1}."""
    return [
        MemberSnapshot(
            member_id=f"m{i}",
            availability=frozenset(availability),
            reliability_score=reliability,
            area=area,
        )
        for i in range(n)
    ]


class TestGroupFormation(unittest.TestCase):
    def test_forms_group_of_ideal_size_from_fresh_pool(self):
        engine = RotationEngine()
        members = make_members(6)
        proposal = engine.generate(RotationInput(members=members))
        self.assertEqual(len(proposal.groups), 1)
        self.assertEqual(proposal.groups[0].size, IDEAL_SIZE)
        self.assertEqual(proposal.unplaced, [])

    def test_all_placed_members_are_unique(self):
        engine = RotationEngine()
        members = make_members(12)
        proposal = engine.generate(RotationInput(members=members))
        placed = [mid for g in proposal.groups for mid in g.member_ids]
        self.assertEqual(len(placed), len(set(placed)), "a member appears twice")

    def test_group_sizes_within_bounds(self):
        engine = RotationEngine()
        members = make_members(14)  # 14 -> should not leave an illegal group
        proposal = engine.generate(RotationInput(members=members))
        for g in proposal.groups:
            self.assertGreaterEqual(g.size, TARGET_MIN)
            self.assertLessEqual(g.size, TARGET_MAX)

    def test_too_few_members_go_unplaced(self):
        engine = RotationEngine()
        members = make_members(3)  # below TARGET_MIN
        proposal = engine.generate(RotationInput(members=members))
        self.assertEqual(proposal.groups, [])
        self.assertEqual(set(proposal.unplaced), {"m0", "m1", "m2"})


class TestRotationContinuityAndNovelty(unittest.TestCase):
    def test_keeps_about_half_of_prior_group(self):
        """With a 6-person prior group and 6 fresh newcomers, the engine should
        keep ~3 of the prior group together (continuity)."""
        engine = RotationEngine(keep_ratio=0.5)
        prior = [f"m{i}" for i in range(6)]
        newcomers = [f"n{i}" for i in range(6)]
        members = (
            make_members(6)  # m0..m5
            + [
                MemberSnapshot(member_id=nid, availability=frozenset({"tue_pm"}))
                for nid in newcomers
            ]
        )
        proposal = engine.generate(
            RotationInput(members=members, prior_groups=[prior])
        )
        # Find the group seeded from the prior group (contains kept members).
        kept_counts = [
            sum(1 for mid in g.member_ids if mid in prior)
            for g in proposal.groups
        ]
        # At least one group keeps ~half (3) of the prior members together.
        self.assertIn(3, kept_counts, f"expected a group keeping ~3; got {kept_counts}")

    def test_prefers_havent_met_members_when_filling(self):
        """A member who has already met the seed should be de-prioritized in
        favor of a member who hasn't met anyone in the group."""
        engine = RotationEngine()
        # Seed group is [a]; candidates b (already met a) and c (new).
        members = [
            MemberSnapshot("a", frozenset({"tue_pm"})),
            MemberSnapshot("b", frozenset({"tue_pm"})),
            MemberSnapshot("c", frozenset({"tue_pm"})),
            MemberSnapshot("d", frozenset({"tue_pm"})),
            MemberSnapshot("e", frozenset({"tue_pm"})),
            MemberSnapshot("f", frozenset({"tue_pm"})),
            MemberSnapshot("g", frozenset({"tue_pm"})),
        ]
        # a has already met b. Prior group [a] so a is kept as the seed.
        met = {"a": {"b"}, "b": {"a"}}
        proposal = engine.generate(
            RotationInput(members=members, prior_groups=[["a"]], met_history=met)
        )
        # The group containing 'a': 'b' should be filled LAST (lowest priority),
        # so with 7 members and IDEAL_SIZE=6, 'b' is the one most likely pushed
        # out. Assert 'a' is grouped and that if b and c compete, c ranks first.
        group_with_a = next(g for g in proposal.groups if "a" in g.member_ids)
        if "b" in group_with_a.member_ids and "c" in group_with_a.member_ids:
            self.assertLess(
                group_with_a.member_ids.index("c"),
                group_with_a.member_ids.index("b"),
                "haven't-met 'c' should be added before already-met 'b'",
            )


class TestConstraints(unittest.TestCase):
    def test_blocked_pair_never_grouped_together(self):
        engine = RotationEngine()
        members = make_members(8)
        # Block m0 and m1 from each other.
        blocks = {"m0": {"m1"}, "m1": {"m0"}}
        proposal = engine.generate(RotationInput(members=members, blocks=blocks))
        for g in proposal.groups:
            self.assertFalse(
                "m0" in g.member_ids and "m1" in g.member_ids,
                "blocked pair m0/m1 ended up in the same group",
            )

    def test_members_split_by_area(self):
        engine = RotationEngine()
        north = make_members(6, area="north")
        south = [
            MemberSnapshot(f"s{i}", frozenset({"tue_pm"}), area="south")
            for i in range(6)
        ]
        proposal = engine.generate(RotationInput(members=north + south))
        for g in proposal.groups:
            areas = set()
            for mid in g.member_ids:
                areas.add("north" if mid.startswith("m") else "south")
            self.assertEqual(len(areas), 1, "a group mixed two areas")


class TestOwnerAssignment(unittest.TestCase):
    def test_every_group_gets_an_owner(self):
        engine = RotationEngine()
        proposal = engine.generate(RotationInput(members=make_members(6)))
        for g in proposal.groups:
            self.assertIsNotNone(g.owner_id)
            self.assertIn(g.owner_id, g.member_ids)

    def test_owner_is_not_previous_owner_when_avoidable(self):
        engine = RotationEngine()
        members = make_members(6)
        # m0 owned last cycle; a different member should be chosen.
        proposal = engine.generate(
            RotationInput(members=members, previous_owners={"m0"})
        )
        g = proposal.groups[0]
        self.assertNotEqual(g.owner_id, "m0")

    def test_owner_falls_back_when_all_were_previous_owners(self):
        engine = RotationEngine()
        members = make_members(6)
        all_ids = {m.member_id for m in members}
        proposal = engine.generate(
            RotationInput(members=members, previous_owners=all_ids)
        )
        g = proposal.groups[0]
        # Everyone owned before, so we still must assign someone.
        self.assertIn(g.owner_id, g.member_ids)


class TestDeterminismAndPurity(unittest.TestCase):
    def test_same_seed_same_result(self):
        engine = RotationEngine()
        members = make_members(12)
        p1 = engine.generate(RotationInput(members=members, seed=42))
        p2 = engine.generate(RotationInput(members=members, seed=42))
        ids1 = [sorted(g.member_ids) for g in p1.groups]
        ids2 = [sorted(g.member_ids) for g in p2.groups]
        self.assertEqual(ids1, ids2)

    def test_does_not_mutate_inputs(self):
        engine = RotationEngine()
        members = make_members(6)
        prior = [["m0", "m1", "m2"]]
        met = {"m0": {"m1"}}
        blocks = {"m0": {"m5"}, "m5": {"m0"}}
        data = RotationInput(
            members=members,
            prior_groups=prior,
            met_history=met,
            blocks=blocks,
            previous_owners={"m0"},
        )
        engine.generate(data)
        # Inputs unchanged.
        self.assertEqual(prior, [["m0", "m1", "m2"]])
        self.assertEqual(met, {"m0": {"m1"}})
        self.assertEqual(blocks, {"m0": {"m5"}, "m5": {"m0"}})


if __name__ == "__main__":
    unittest.main()
