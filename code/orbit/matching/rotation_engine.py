"""
Orbit — Rotating Social Club
THE CRITICAL FILE: the rotation engine.

This implements Orbit's core promise (docs 04 sec.6 and 07 sec.5):
  - form groups of TARGET_MIN..TARGET_MAX members,
  - each cycle KEEP ~50% of a prior group (continuity / bonds) and
    SWAP ~50% for members you have NOT met (novelty / anti-clique),
  - respect HARD constraints (blocked pairs, availability bucket),
  - assign a FAIR next owner (never the same person two cycles running).

Design goals:
  * Deterministic given a seed  -> testable & reviewable by a human Steward.
  * Explainable (greedy, no black box) for the MVP; a weighted scorer can
    replace `_fill_group` later (V1) without changing the interface.
  * Pure standard library.

The engine is PURE: it takes plain inputs and returns a proposal. It performs
NO I/O and mutates none of its inputs, so it is trivially unit-testable.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field, replace
from typing import Iterable, Optional

# Group-size sweet spot (doc 01 failure mode F8: scale mismatch).
TARGET_MIN = 6
TARGET_MAX = 8
IDEAL_SIZE = 6


@dataclass(frozen=True)
class MemberSnapshot:
    """The minimal, immutable view of a member the engine needs.

    Kept separate from the domain `Member` so the engine has no dependency
    on storage or the wider model — it is a pure function of these snapshots.
    """

    member_id: str
    availability: frozenset[str]
    reliability_score: int = 100
    niche: Optional[str] = None
    # Coarse area key for proximity bucketing (e.g. a geohash prefix or zip).
    area: str = "default"


@dataclass
class RotationInput:
    """Everything the engine needs for one cycle."""

    members: list[MemberSnapshot]
    # Prior cycle's groups: list of member-id lists.
    prior_groups: list[list[str]] = field(default_factory=list)
    # Who each member has already met (member_id -> set of member_ids).
    met_history: dict[str, set[str]] = field(default_factory=dict)
    # Symmetric hard block: member_id -> set of member_ids they must NOT join.
    blocks: dict[str, set[str]] = field(default_factory=dict)
    # Members who owned last cycle (excluded from being owner again now).
    previous_owners: set[str] = field(default_factory=set)
    # Deterministic seed for reproducible proposals.
    seed: int = 0


@dataclass
class ProposedGroup:
    """One group in the proposal: its members and its nominated owner."""

    member_ids: list[str]
    owner_id: Optional[str]

    @property
    def size(self) -> int:
        return len(self.member_ids)


@dataclass
class RotationProposal:
    """The engine's output. Committed only after Rotation Steward review (FR-14)."""

    groups: list[ProposedGroup]
    # Members who could not be placed (e.g. tiny leftover in an area bucket).
    unplaced: list[str] = field(default_factory=list)


class RotationEngine:
    """Greedy, constraint-aware, keep-50/swap-50 rotation.

    The candidate scoring used to fill groups is pluggable behind a stable
    interface:

      * default (``scorer=None``) uses the explainable MVP score
        (anti-clique novelty + availability overlap + niche affinity).
      * pass a :class:`WeightedScorer` (see below) for the V1 weighted model
        (adds reliability-balancing and configurable weights) WITHOUT changing
        any calling code.

    Usage:
        engine = RotationEngine()                      # MVP scoring
        engine = RotationEngine(scorer=WeightedScorer())   # V1 scoring
        proposal = engine.generate(rotation_input)
    """

    def __init__(
        self,
        keep_ratio: float = 0.5,
        scorer: "Optional[CandidateScorer]" = None,
    ) -> None:
        if not 0.0 <= keep_ratio <= 1.0:
            raise ValueError("keep_ratio must be between 0 and 1")
        self.keep_ratio = keep_ratio
        # None -> use the built-in MVP score (self._candidate_score).
        self.scorer = scorer

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def generate(self, data: RotationInput) -> RotationProposal:
        """Produce a group proposal for one cycle.

        Steps:
          1. Bucket eligible members by (area, availability-overlap).
          2. Within each bucket, seed new groups by keeping ~50% of each
             prior group, then fill the rest with 'haven't-met' members.
          3. Absorb leftover members into balanced groups.
          4. Assign a fair owner to each group.
        """
        rng = random.Random(data.seed)
        member_by_id = {m.member_id: m for m in data.members}

        # Anyone who shared a prior group has met each other, whether or not
        # the caller's met_history says so explicitly. Without this, the
        # 'swap ~50%' promise breaks: the dropped half of a prior group has
        # no lower score than a true newcomer, so ties get broken by id and
        # the dropped members can get filled straight back into their own
        # old group instead of making room for someone new.
        data_for_fill = replace(data, met_history=self._effective_met_history(data))

        proposed: list[ProposedGroup] = []
        unplaced: list[str] = []

        for bucket_members in self._bucket_by_area(data.members):
            groups = self._form_groups_for_bucket(
                bucket_members=bucket_members,
                data=data_for_fill,
                member_by_id=member_by_id,
                rng=rng,
            )
            proposed.extend(groups.placed)
            unplaced.extend(groups.leftover)

        # Assign owners after all groups are formed.
        for g in proposed:
            g.owner_id = self._pick_owner(
                g.member_ids, data.previous_owners, member_by_id
            )

        return RotationProposal(groups=proposed, unplaced=unplaced)

    def _effective_met_history(self, data: RotationInput) -> dict[str, set[str]]:
        """Merge explicit met_history with history implied by prior_groups.

        Returns a new dict of new sets; never mutates ``data``.
        """
        effective: dict[str, set[str]] = {
            mid: set(peers) for mid, peers in data.met_history.items()
        }
        for pg in data.prior_groups:
            for mid in pg:
                effective.setdefault(mid, set()).update(p for p in pg if p != mid)
        return effective

    # ------------------------------------------------------------------ #
    # Step 1 — bucketing
    # ------------------------------------------------------------------ #
    def _bucket_by_area(
        self, members: Iterable[MemberSnapshot]
    ) -> list[list[MemberSnapshot]]:
        """Group eligible members by coarse area.

        Availability is handled softly during filling (we prefer overlap but
        do not hard-split by it, to avoid tiny unmatchable buckets).
        """
        buckets: dict[str, list[MemberSnapshot]] = {}
        for m in members:
            buckets.setdefault(m.area, []).append(m)
        # Stable order for determinism.
        return [buckets[k] for k in sorted(buckets.keys())]

    # ------------------------------------------------------------------ #
    # Step 2 & 3 — form groups within a bucket
    # ------------------------------------------------------------------ #
    @dataclass
    class _BucketResult:
        placed: list["ProposedGroup"]
        leftover: list[str]

    def _form_groups_for_bucket(
        self,
        bucket_members: list[MemberSnapshot],
        data: RotationInput,
        member_by_id: dict[str, MemberSnapshot],
        rng: random.Random,
    ) -> "_BucketResult":
        bucket_ids = {m.member_id for m in bucket_members}
        available: set[str] = set(bucket_ids)

        # Prior groups restricted to this bucket, largest first for stability.
        prior_here = [
            [mid for mid in pg if mid in bucket_ids]
            for pg in data.prior_groups
        ]
        prior_here = [pg for pg in prior_here if pg]
        prior_here.sort(key=lambda pg: (-len(pg), pg[0] if pg else ""))

        new_groups: list[list[str]] = []

        # --- Seed each new group by KEEPING ~50% of a prior group ---------
        for pg in prior_here:
            keepers = self._pick_keepers(pg, available, member_by_id, rng)
            if not keepers:
                continue
            for k in keepers:
                available.discard(k)
            new_groups.append(list(keepers))

        # If there were no prior groups, seed empty groups sized to the pool.
        if not new_groups:
            n_groups = max(1, round(len(available) / IDEAL_SIZE))
            new_groups = [[] for _ in range(n_groups)]

        # Capacity check: seeded groups can absorb at most this many members.
        # If the pool is larger (membership grew), open additional empty
        # groups so newcomers form fresh groups instead of being stranded.
        seeded_capacity = sum(TARGET_MAX - len(g) for g in new_groups)
        surplus = len(available) - seeded_capacity
        if surplus > 0:
            extra_groups = max(1, round(surplus / IDEAL_SIZE))
            new_groups.extend([] for _ in range(extra_groups))

        # --- Fill each group with HAVEN'T-MET members (anti-clique) -------
        # Fill toward IDEAL_SIZE first (round-robin fairness is approximated by
        # filling seeded groups then new ones); leftover absorption balances up
        # to TARGET_MAX afterwards.
        for group in new_groups:
            self._fill_group(group, available, data, member_by_id)

        # --- Absorb any leftover members ----------------------------------
        leftover = sorted(available)
        leftover = self._absorb_leftover(new_groups, leftover, data, member_by_id)

        # Drop groups that ended up too small; their members become leftover
        # to be merged (FR-16). In MVP we surface them as unplaced.
        placed: list[ProposedGroup] = []
        final_leftover: list[str] = []
        for group in new_groups:
            if len(group) >= TARGET_MIN:
                placed.append(ProposedGroup(member_ids=group, owner_id=None))
            else:
                final_leftover.extend(group)
        final_leftover.extend(leftover)

        return self._BucketResult(placed=placed, leftover=sorted(set(final_leftover)))

    def _pick_keepers(
        self,
        prior_group: list[str],
        available: set[str],
        member_by_id: dict[str, MemberSnapshot],
        rng: random.Random,
    ) -> list[str]:
        """Keep ~keep_ratio of a prior group for continuity.

        Preference: keep the most reliable members (they anchor the group).
        Only members still eligible/available can be kept.
        """
        candidates = [mid for mid in prior_group if mid in available]
        if not candidates:
            return []
        keep_n = max(1, round(len(candidates) * self.keep_ratio))
        keep_n = min(keep_n, TARGET_MAX)
        # Sort by reliability desc, then id for determinism.
        candidates.sort(
            key=lambda mid: (-member_by_id[mid].reliability_score, mid)
        )
        return candidates[:keep_n]

    def _fill_group(
        self,
        group: list[str],
        available: set[str],
        data: RotationInput,
        member_by_id: dict[str, MemberSnapshot],
    ) -> None:
        """Fill a group toward IDEAL_SIZE with the best available candidates.

        Candidate score (higher is better):
          + strongly prefer members who have NOT met anyone already in group
          + prefer availability overlap with the group
          + prefer matching niche
        Hard constraint: never add a member blocked with anyone in the group.
        """
        while len(group) < IDEAL_SIZE and available:
            best_id: Optional[str] = None
            best_score = float("-inf")
            for cand in sorted(available):  # sorted -> deterministic tie-break
                if self._violates_block(cand, group, data.blocks):
                    continue
                if self.scorer is not None:
                    score = self.scorer.score(cand, group, data, member_by_id)
                else:
                    score = self._candidate_score(cand, group, data, member_by_id)
                if score > best_score:
                    best_score = score
                    best_id = cand
            if best_id is None:
                break  # nobody can legally join (all blocked)
            group.append(best_id)
            available.discard(best_id)

    def _candidate_score(
        self,
        cand: str,
        group: list[str],
        data: RotationInput,
        member_by_id: dict[str, MemberSnapshot],
    ) -> float:
        met = data.met_history.get(cand, set())
        # Anti-clique: how many in the group has the candidate already met?
        already_met = sum(1 for mid in group if mid in met)
        novelty = -5.0 * already_met  # heavily penalize re-meeting

        cand_snap = member_by_id[cand]
        # Availability overlap with the group (soft preference).
        overlap = 0
        for mid in group:
            overlap += len(cand_snap.availability & member_by_id[mid].availability)
        avail_bonus = 0.5 * overlap

        # Niche affinity (soft preference).
        niche_bonus = 0.0
        if cand_snap.niche is not None:
            same = sum(
                1 for mid in group if member_by_id[mid].niche == cand_snap.niche
            )
            niche_bonus = 0.3 * same

        return novelty + avail_bonus + niche_bonus

    def _absorb_leftover(
        self,
        groups: list[list[str]],
        leftover: list[str],
        data: RotationInput,
        member_by_id: dict[str, MemberSnapshot],
    ) -> list[str]:
        """Place leftover members into groups that are still below TARGET_MAX."""
        remaining: list[str] = []
        for mid in leftover:
            placed = False
            # Prefer the smallest legal group (balance sizes).
            for group in sorted(groups, key=len):
                if len(group) >= TARGET_MAX:
                    continue
                if self._violates_block(mid, group, data.blocks):
                    continue
                group.append(mid)
                placed = True
                break
            if not placed:
                remaining.append(mid)
        return remaining

    # ------------------------------------------------------------------ #
    # Step 4 — fair owner assignment (FR-20)
    # ------------------------------------------------------------------ #
    def _pick_owner(
        self,
        member_ids: list[str],
        previous_owners: set[str],
        member_by_id: dict[str, MemberSnapshot],
    ) -> Optional[str]:
        """Nominate a fair owner: never someone who owned last cycle.

        Among eligible members, prefer the most reliable (they can host well),
        with id as a deterministic tie-break. If everyone owned last cycle,
        fall back to the whole group so the group still gets an owner.
        """
        if not member_ids:
            return None
        eligible = [mid for mid in member_ids if mid not in previous_owners]
        pool = eligible if eligible else list(member_ids)
        pool.sort(key=lambda mid: (-member_by_id[mid].reliability_score, mid))
        return pool[0]

    # ------------------------------------------------------------------ #
    # Constraints
    # ------------------------------------------------------------------ #
    @staticmethod
    def _violates_block(
        cand: str, group: list[str], blocks: dict[str, set[str]]
    ) -> bool:
        """True if cand is blocked with anyone already in the group (symmetric)."""
        cand_blocks = blocks.get(cand, set())
        for mid in group:
            if mid in cand_blocks or cand in blocks.get(mid, set()):
                return True
        return False


# --------------------------------------------------------------------------- #
# Pluggable candidate scoring (V1 weighted matching)
# --------------------------------------------------------------------------- #
class CandidateScorer:
    """Interface for scoring a candidate's fit for a partially-filled group.

    Implementations return a float where HIGHER is a better fit. The engine
    picks the highest-scoring legal (non-blocked) candidate each step.
    Implement :meth:`score` with the same signature as below.
    """

    def score(
        self,
        cand: str,
        group: list[str],
        data: "RotationInput",
        member_by_id: dict[str, "MemberSnapshot"],
    ) -> float:  # pragma: no cover - interface
        raise NotImplementedError


class WeightedScorer(CandidateScorer):
    """V1 weighted scorer — same interface, richer, tunable model.

    Adds to the MVP factors a **reliability-balancing** term so groups don't
    accidentally concentrate all the flaky (or all the ultra-reliable) members
    in one group, which keeps every group viable. All weights are tunable, so
    this is the hook for the V2 "learn weights from attendance feedback" step
    (doc 04 sec.6) — feed tuned weights in here without touching the engine.

    Factors (each multiplied by its weight):
      * novelty:    negative per already-met member in the group (anti-clique)
      * availability: overlap of availability tokens with the group
      * niche:      same-niche members already in the group
      * reliability_balance: prefers candidates whose reliability pulls the
        group's average toward a healthy target (default 100), so weak groups
        get anchored and strong groups share the load.
    """

    def __init__(
        self,
        novelty_weight: float = 5.0,
        availability_weight: float = 0.5,
        niche_weight: float = 0.3,
        reliability_weight: float = 0.02,
        reliability_target: float = 100.0,
    ) -> None:
        self.novelty_weight = novelty_weight
        self.availability_weight = availability_weight
        self.niche_weight = niche_weight
        self.reliability_weight = reliability_weight
        self.reliability_target = reliability_target

    def score(
        self,
        cand: str,
        group: list[str],
        data: "RotationInput",
        member_by_id: dict[str, "MemberSnapshot"],
    ) -> float:
        cand_snap = member_by_id[cand]

        # Anti-clique novelty (same shape as MVP, but weighted).
        met = data.met_history.get(cand, set())
        already_met = sum(1 for mid in group if mid in met)
        novelty = -self.novelty_weight * already_met

        # Availability overlap.
        overlap = 0
        for mid in group:
            overlap += len(cand_snap.availability & member_by_id[mid].availability)
        avail = self.availability_weight * overlap

        # Niche affinity.
        niche = 0.0
        if cand_snap.niche is not None:
            same = sum(
                1 for mid in group if member_by_id[mid].niche == cand_snap.niche
            )
            niche = self.niche_weight * same

        # Reliability balancing: reward candidates that move the group's
        # average reliability toward the target. If the group is currently
        # below target, a reliable candidate scores higher; if already at/above,
        # the term contributes ~0 so novelty still dominates.
        balance = 0.0
        if group:
            cur_avg = sum(
                member_by_id[mid].reliability_score for mid in group
            ) / len(group)
            gap = self.reliability_target - cur_avg  # >0 means group is weak
            # A candidate helps if their score is above the current average.
            lift = cand_snap.reliability_score - cur_avg
            balance = self.reliability_weight * max(0.0, gap) * lift / 100.0

        return novelty + avail + niche + balance
