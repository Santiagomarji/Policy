"""
Orbit — JSON file persistence repository.

Gives Orbit independent, dependency-free durability: all state lives in a
single JSON file on disk, so data survives process restarts with NO database
and NO cloud service. This keeps Orbit fully self-hostable outside any
specific provider.

It subclasses :class:`InMemoryRepository`, so every service works unchanged.
Writes are persisted via an atomic replace (write temp file, then os.replace)
so a crash mid-write cannot corrupt the store.

For higher scale, swap this for the PostgreSQL schema in
docs/07_Database_Design.md (and the migration in code/migrations/) behind the
same method names — no service code changes.
"""
from __future__ import annotations

import json
import os
import tempfile
from typing import Any

from ..domain.models import Club, Cycle, Event, Group, Member, Rsvp, Venue
from . import serialization as ser
from .repository import InMemoryRepository


class JsonFileRepository(InMemoryRepository):
    """An InMemoryRepository that loads from and saves to a JSON file.

    Args:
        path: Path to the JSON store file. Created on first save if absent.
        autosave: If True (default), every mutating ``add_*`` / history call
            persists immediately. Set False for bulk loads, then call
            :meth:`save` once.
    """

    def __init__(self, path: str, autosave: bool = True) -> None:
        super().__init__()
        self.path = path
        self.autosave = autosave
        if os.path.exists(path):
            self.load()

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #
    def to_dict(self) -> dict[str, Any]:
        """Serialize the entire store to a JSON-safe dict."""
        return {
            "version": 2,
            "clubs": [ser.club_to_dict(c) for c in self.clubs.values()],
            "members": [ser.member_to_dict(m, include_token=True) for m in self.members.values()],
            "cycles": [ser.cycle_to_dict(c) for c in self.cycles.values()],
            "groups": [ser.group_to_dict(g) for g in self.groups.values()],
            "events": [ser.event_to_dict(e) for e in self.events.values()],
            "rsvps": [ser.rsvp_to_dict(r) for r in self.rsvps.values()],
            "venues": [ser.venue_to_dict(v) for v in self.venues.values()],
            "ratings": [ser.rating_to_dict(r) for r in self.ratings.values()],
            "volunteer_roles": [
                ser.volunteer_role_to_dict(r) for r in self.volunteer_roles.values()
            ],
            "subscriptions": [
                ser.subscription_to_dict(s) for s in self.subscriptions.values()
            ],
            "payments": [ser.payment_to_dict(p) for p in self.payments.values()],
            "notifications": [
                ser.notification_to_dict(n) for n in self.notifications.values()
            ],
            "met_history": {k: sorted(v) for k, v in self.met_history.items()},
            "blocks": {k: sorted(v) for k, v in self.blocks.items()},
        }

    def load_from_dict(self, data: dict[str, Any]) -> None:
        """Populate the store from a serialized dict (replaces current state)."""
        self.clubs = {c["id"]: ser.club_from_dict(c) for c in data.get("clubs", [])}
        self.members = {
            m["id"]: ser.member_from_dict(m) for m in data.get("members", [])
        }
        self.cycles = {c["id"]: ser.cycle_from_dict(c) for c in data.get("cycles", [])}
        self.groups = {g["id"]: ser.group_from_dict(g) for g in data.get("groups", [])}
        self.events = {e["id"]: ser.event_from_dict(e) for e in data.get("events", [])}
        self.rsvps = {r["id"]: ser.rsvp_from_dict(r) for r in data.get("rsvps", [])}
        self.venues = {v["id"]: ser.venue_from_dict(v) for v in data.get("venues", [])}
        self.ratings = {
            r["id"]: ser.rating_from_dict(r) for r in data.get("ratings", [])
        }
        self.volunteer_roles = {
            r["id"]: ser.volunteer_role_from_dict(r)
            for r in data.get("volunteer_roles", [])
        }
        self.subscriptions = {
            s["id"]: ser.subscription_from_dict(s)
            for s in data.get("subscriptions", [])
        }
        self.payments = {
            p["id"]: ser.payment_from_dict(p) for p in data.get("payments", [])
        }
        self.notifications = {
            n["id"]: ser.notification_from_dict(n)
            for n in data.get("notifications", [])
        }
        self.met_history = {
            k: set(v) for k, v in data.get("met_history", {}).items()
        }
        self.blocks = {k: set(v) for k, v in data.get("blocks", {}).items()}
        # Ensure every member has a met_history bucket.
        for mid in self.members:
            self.met_history.setdefault(mid, set())

    def load(self) -> None:
        """Read the JSON file from disk into memory."""
        with open(self.path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        self.load_from_dict(data)

    def save(self) -> None:
        """Atomically write the store to disk.

        Writes to a temp file in the same directory, then ``os.replace`` swaps
        it in — an atomic operation on the same filesystem, so a partial write
        can never corrupt the live store.
        """
        directory = os.path.dirname(os.path.abspath(self.path)) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.to_dict(), fh, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)
        except BaseException:
            # Clean up the temp file on any failure, then re-raise.
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

    def _maybe_save(self) -> None:
        if self.autosave:
            self.save()

    # ------------------------------------------------------------------ #
    # Overrides: persist after each mutation
    # ------------------------------------------------------------------ #
    def add_club(self, club: Club) -> Club:
        super().add_club(club)
        self._maybe_save()
        return club

    def add_member(self, member: Member) -> Member:
        super().add_member(member)
        self._maybe_save()
        return member

    def add_cycle(self, cycle: Cycle) -> Cycle:
        super().add_cycle(cycle)
        self._maybe_save()
        return cycle

    def add_group(self, group: Group) -> Group:
        super().add_group(group)
        self._maybe_save()
        return group

    def add_event(self, event: Event) -> Event:
        super().add_event(event)
        self._maybe_save()
        return event

    def add_rsvp(self, rsvp: Rsvp) -> Rsvp:
        super().add_rsvp(rsvp)
        self._maybe_save()
        return rsvp

    def add_venue(self, venue: Venue) -> Venue:
        super().add_venue(venue)
        self._maybe_save()
        return venue

    def add_volunteer_role(self, role):  # type: ignore[no-untyped-def]
        result = super().add_volunteer_role(role)
        self._maybe_save()
        return result

    def add_subscription(self, sub):  # type: ignore[no-untyped-def]
        result = super().add_subscription(sub)
        self._maybe_save()
        return result

    def add_payment(self, payment):  # type: ignore[no-untyped-def]
        result = super().add_payment(payment)
        self._maybe_save()
        return result

    def add_notification(self, n):  # type: ignore[no-untyped-def]
        result = super().add_notification(n)
        self._maybe_save()
        return result

    def add_rating(self, rating):  # type: ignore[no-untyped-def]
        result = super().add_rating(rating)
        self._maybe_save()
        return result

    def record_met(self, member_ids: list[str]) -> None:
        super().record_met(member_ids)
        self._maybe_save()

    def add_block(self, a: str, b: str) -> None:
        super().add_block(a, b)
        self._maybe_save()

    # ------------------------------------------------------------------ #
    # Context manager sugar for bulk operations
    # ------------------------------------------------------------------ #
    def __enter__(self) -> "JsonFileRepository":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        # Persist on clean exit regardless of autosave setting.
        if exc_type is None:
            self.save()
