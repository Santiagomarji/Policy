"""
Tests for persistence (JsonFileRepository) and serialization round-trips.

Uses a temp directory so no real files are left behind.
"""
import os
import tempfile
import unittest
from datetime import date, datetime

from orbit.domain.enums import CycleStatus, MemberStatus
from orbit.domain.models import GeoPoint, Venue
from orbit.services.club_service import ClubService
from orbit.services.json_repository import JsonFileRepository
from orbit.services.matching_service import MatchingService


class TestJsonRepository(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "orbit_test.json")

    def tearDown(self):
        # Clean up any files created.
        for f in os.listdir(self.tmp):
            os.remove(os.path.join(self.tmp, f))
        os.rmdir(self.tmp)

    def test_saves_and_reloads(self):
        repo = JsonFileRepository(self.path)
        clubs = ClubService(repo)
        club = clubs.create_club("Persist Club", "Diskville", min_density=6)
        clubs.register_member(
            club.id, "Sam", "sam@x.io",
            availability={"tue_pm"}, location=GeoPoint(1.0, 2.0), niche="creatives",
        )
        self.assertTrue(os.path.exists(self.path))

        # Reload into a fresh repository instance.
        repo2 = JsonFileRepository(self.path)
        self.assertEqual(len(repo2.clubs), 1)
        self.assertEqual(len(repo2.members_for_club(club.id)), 1)
        m = repo2.members_for_club(club.id)[0]
        self.assertEqual(m.name, "Sam")
        self.assertEqual(m.preference.niche, "creatives")
        self.assertEqual(m.preference.availability, {"tue_pm"})
        self.assertIsNotNone(m.preference.location)
        self.assertEqual(m.preference.location.lat, 1.0)
        self.assertEqual(m.status, MemberStatus.ACTIVE)

    def test_full_cycle_survives_reload(self):
        repo = JsonFileRepository(self.path)
        clubs = ClubService(repo)
        matching = MatchingService(repo)
        club = clubs.create_club("C", "City", min_density=6)
        for i in range(6):
            clubs.register_member(
                club.id, f"M{i}", f"m{i}@x.io",
                availability={"tue_pm"}, location=GeoPoint(1.0, 1.0),
            )
        cycle = matching.create_cycle(club.id, date(2026, 1, 6))
        proposal = matching.generate_proposal(cycle.id, seed=1)
        matching.commit_proposal(cycle.id, proposal)

        # Reload; groups, membership, met_history must persist.
        repo2 = JsonFileRepository(self.path)
        self.assertEqual(repo2.cycles[cycle.id].status, CycleStatus.COMMITTED)
        groups = repo2.groups_for_cycle(cycle.id)
        self.assertEqual(len(groups), 1)
        first = groups[0].member_ids[0]
        self.assertEqual(
            repo2.met_history[first], set(groups[0].member_ids) - {first}
        )

    def test_blocks_persist(self):
        repo = JsonFileRepository(self.path)
        clubs = ClubService(repo)
        club = clubs.create_club("C", "City")
        a = clubs.register_member(club.id, "A", "a@x.io")
        b = clubs.register_member(club.id, "B", "b@x.io")
        repo.add_block(a.id, b.id)

        repo2 = JsonFileRepository(self.path)
        self.assertIn(b.id, repo2.blocks[a.id])
        self.assertIn(a.id, repo2.blocks[b.id])  # symmetric

    def test_atomic_save_no_tmp_left(self):
        repo = JsonFileRepository(self.path)
        ClubService(repo).create_club("C", "City")
        # Only the store file should remain (no .tmp leftovers).
        files = os.listdir(self.tmp)
        self.assertEqual(files, ["orbit_test.json"])

    def test_venue_partner_persists(self):
        repo = JsonFileRepository(self.path)
        club = ClubService(repo).create_club("C", "City")
        repo.add_venue(Venue(club_id=club.id, name="Bar", partner=True, vetted=True))
        repo2 = JsonFileRepository(self.path)
        self.assertIsNotNone(repo2.partner_venue(club.id))
        self.assertEqual(repo2.partner_venue(club.id).name, "Bar")


if __name__ == "__main__":
    unittest.main()
