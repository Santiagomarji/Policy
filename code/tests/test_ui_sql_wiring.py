"""
Tests for the pieces added in the UI + SQL wiring pass:

  * token auth (401 on writes when a token is configured)
  * GET /clubs/{id}/cycles listing
  * availability sent as a comma/space string is normalized
  * repository factory fallback (Postgres requested but no driver -> JSON)
  * _norm_availability helper
"""
import os
import tempfile
import unittest

from orbit.services.api import OrbitRouter, _norm_availability
from orbit.services.json_repository import JsonFileRepository


class TestNormAvailability(unittest.TestCase):
    def test_none_and_empty(self):
        self.assertEqual(_norm_availability(None), set())
        self.assertEqual(_norm_availability(""), set())

    def test_comma_string(self):
        self.assertEqual(_norm_availability("tue_pm, thu_pm"), {"tue_pm", "thu_pm"})

    def test_space_string(self):
        self.assertEqual(_norm_availability("tue_pm thu_pm"), {"tue_pm", "thu_pm"})

    def test_list_passthrough(self):
        self.assertEqual(_norm_availability(["tue_pm", "thu_pm"]),
                         {"tue_pm", "thu_pm"})

    def test_strips_blanks(self):
        self.assertEqual(_norm_availability("tue_pm,,  ,thu_pm"),
                         {"tue_pm", "thu_pm"})


class _RouterFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "auth_test.json")
        self.repo = JsonFileRepository(self.path)

    def tearDown(self):
        for f in os.listdir(self.tmp):
            os.remove(os.path.join(self.tmp, f))
        os.rmdir(self.tmp)


class TestAuth(_RouterFixture):
    def test_no_token_configured_allows_writes(self):
        router = OrbitRouter(self.repo)  # auth_token=None
        status, _ = router.handle("POST", "/clubs",
                                  {"name": "X", "city": "Y"})
        self.assertEqual(status, 201)

    def test_write_requires_token_when_configured(self):
        router = OrbitRouter(self.repo, auth_token="secret")
        # No token -> 401.
        status, body = router.handle("POST", "/clubs",
                                     {"name": "X", "city": "Y"})
        self.assertEqual(status, 401)
        self.assertIn("unauthorized", body["error"])

    def test_write_succeeds_with_correct_token(self):
        router = OrbitRouter(self.repo, auth_token="secret")
        status, _ = router.handle("POST", "/clubs",
                                  {"name": "X", "city": "Y"}, token="secret")
        self.assertEqual(status, 201)

    def test_read_allowed_without_token(self):
        router = OrbitRouter(self.repo, auth_token="secret")
        status, _ = router.handle("GET", "/clubs", None)
        self.assertEqual(status, 200)


class TestCyclesListAndAvailability(_RouterFixture):
    def _club(self, router):
        _, c = router.handle("POST", "/clubs",
                             {"name": "C", "city": "City", "min_density": 6})
        return c["id"]

    def test_list_cycles(self):
        router = OrbitRouter(self.repo)
        cid = self._club(router)
        # No cycles yet.
        status, body = router.handle("GET", f"/clubs/{cid}/cycles", None)
        self.assertEqual(status, 200)
        self.assertEqual(body, [])
        # Create two cycles; they come back sorted by start_date.
        router.handle("POST", f"/clubs/{cid}/cycles", {"start_date": "2026-02-01"})
        router.handle("POST", f"/clubs/{cid}/cycles", {"start_date": "2026-01-01"})
        status, body = router.handle("GET", f"/clubs/{cid}/cycles", None)
        self.assertEqual(status, 200)
        self.assertEqual(len(body), 2)
        self.assertEqual(body[0]["start_date"], "2026-01-01")
        self.assertEqual(body[1]["start_date"], "2026-02-01")

    def test_member_availability_as_string(self):
        router = OrbitRouter(self.repo)
        cid = self._club(router)
        status, member = router.handle(
            "POST", f"/clubs/{cid}/members",
            {"name": "Sam", "email": "s@x.io", "availability": "tue_pm, thu_pm"},
        )
        self.assertEqual(status, 201)
        # Availability was normalized into a set -> serialized as sorted list.
        self.assertEqual(
            set(member["preference"]["availability"]), {"tue_pm", "thu_pm"}
        )

    def test_bad_latlng_returns_400(self):
        router = OrbitRouter(self.repo)
        cid = self._club(router)
        status, body = router.handle(
            "POST", f"/clubs/{cid}/members",
            {"name": "Sam", "email": "s@x.io", "lat": "abc", "lng": "def"},
        )
        self.assertEqual(status, 400)


class TestRepositoryFactory(unittest.TestCase):
    def setUp(self):
        # Snapshot env so we can restore it.
        self._env = dict(os.environ)
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        for f in os.listdir(self.tmp):
            os.remove(os.path.join(self.tmp, f))
        os.rmdir(self.tmp)

    def test_defaults_to_json(self):
        from orbit.services.repository_factory import make_repository
        from orbit.services.json_repository import JsonFileRepository as JFR

        os.environ.pop("DATABASE_URL", None)
        os.environ.pop("ORBIT_DB_BACKEND", None)
        os.environ["ORBIT_DB"] = os.path.join(self.tmp, "factory.json")
        repo = make_repository()
        self.assertIsInstance(repo, JFR)

    def test_postgres_without_driver_falls_back_to_json(self):
        from orbit.services import repository_factory as rf
        from orbit.services.json_repository import JsonFileRepository as JFR

        os.environ["DATABASE_URL"] = "postgres://u:p@localhost:5432/orbit"
        os.environ["ORBIT_DB"] = os.path.join(self.tmp, "factory.json")
        # Force "driver missing" regardless of the real environment.
        original = rf._postgres_available
        rf._postgres_available = lambda: False
        try:
            repo = rf.make_repository()
        finally:
            rf._postgres_available = original
        self.assertIsInstance(repo, JFR)

    def test_flush_repository_noop_on_json(self):
        from orbit.services.repository_factory import flush_repository
        from orbit.services.json_repository import JsonFileRepository as JFR

        repo = JFR(os.path.join(self.tmp, "factory.json"))
        # Should not raise even though JSON repo has no flush()/clear_cache().
        flush_repository(repo)

    def test_redact_hides_credentials(self):
        from orbit.services.repository_factory import _redact
        red = _redact("postgres://user:secret@host:5432/db")
        self.assertNotIn("secret", red)
        self.assertIn("host:5432/db", red)


if __name__ == "__main__":
    unittest.main()
