"""
Tests for the optimizer logic in espn_lineup.py.

Run with:
    python -m pytest test_espn_lineup.py -v
  or:
    python -m unittest test_espn_lineup.py
"""
import datetime
import unittest
from unittest.mock import MagicMock, patch

import espn_lineup as el

# ── Test helpers ──────────────────────────────────────────────────────────────

_next_id = 1


def make_entry(name, slot, eligible_slots, pro_team_id=1):
    global _next_id
    pid = _next_id
    _next_id += 1
    return {
        "lineupSlotId": slot,
        "playerPoolEntry": {
            "player": {
                "fullName": name,
                "id": pid,
                "eligibleSlots": eligible_slots,
                "proTeamId": pro_team_id,
            }
        },
    }


# ESPN eligible-slot lists derived from the docstrings in espn_lineup.py:
#   SP: eligible for SP(13), RP(14), P(15), BE(16)  — is_sp() looks for 14
#   RP: eligible for SP(13),         P(15), BE(16)  — is_rp() looks for 13 w/o 14
SP_ELIGIBLE = [el.SLOT_SP, el.SLOT_RP, el.SLOT_P, el.SLOT_BE]
RP_ELIGIBLE = [el.SLOT_SP, el.SLOT_P, el.SLOT_BE]


def make_sp(name, slot=el.SLOT_SP, pro_team_id=1):
    return make_entry(name, slot, SP_ELIGIBLE, pro_team_id)


def make_rp(name, slot=el.SLOT_RP, pro_team_id=1):
    return make_entry(name, slot, RP_ELIGIBLE, pro_team_id)


def make_slot_counts(sp=7, rp=1, p=1):
    return {el.SLOT_SP: sp, el.SLOT_RP: rp, el.SLOT_P: p, el.SLOT_BE: 5, el.SLOT_IL: 2}


# ── TestRoleDetection ─────────────────────────────────────────────────────────

class TestRoleDetection(unittest.TestCase):

    def test_sp_detected(self):
        e = make_sp("Gerrit Cole")
        self.assertTrue(el.is_sp(e))
        self.assertFalse(el.is_rp(e))

    def test_rp_detected(self):
        e = make_rp("Emmanuel Clase")
        self.assertFalse(el.is_sp(e))
        self.assertTrue(el.is_rp(e))

    def test_sp_on_bench_still_sp(self):
        e = make_sp("Gerrit Cole", slot=el.SLOT_BE)
        self.assertTrue(el.is_sp(e))

    def test_rp_on_bench_still_rp(self):
        e = make_rp("Emmanuel Clase", slot=el.SLOT_BE)
        self.assertTrue(el.is_rp(e))


# ── TestHasStart ──────────────────────────────────────────────────────────────

class TestHasStart(unittest.TestCase):

    def test_exact_match(self):
        e = make_sp("Gerrit Cole")
        self.assertTrue(el.has_start(e, 1, {1: {"gerrit cole"}}))

    def test_case_insensitive(self):
        e = make_sp("GERRIT COLE")
        self.assertTrue(el.has_start(e, 1, {1: {"gerrit cole"}}))

    def test_no_match(self):
        e = make_sp("Gerrit Cole")
        self.assertFalse(el.has_start(e, 1, {1: {"shane bieber"}}))

    def test_wrong_period(self):
        e = make_sp("Gerrit Cole")
        self.assertFalse(el.has_start(e, 2, {1: {"gerrit cole"}}))

    def test_none_probable_starters(self):
        e = make_sp("Gerrit Cole")
        self.assertFalse(el.has_start(e, 1, None))

    def test_empty_probable_starters(self):
        e = make_sp("Gerrit Cole")
        self.assertFalse(el.has_start(e, 1, {}))

    # ESPN PP fallback tests

    def _add_espn_probable(self, entry):
        """Add ESPN starterStatusByProGame PROBABLE flag to a test entry."""
        entry["playerPoolEntry"]["player"]["starterStatusByProGame"] = {"401999999": "PROBABLE"}
        return entry

    def test_espn_fallback_when_no_mlb_data(self):
        """ESPN PP flag used when MLB Stats API has no starters and game_period_map confirms the game."""
        e = self._add_espn_probable(make_sp("Gerrit Cole", pro_team_id=5))
        # game_period_map says game 401999999 is on period 8
        self.assertTrue(el.has_start(e, 8, {}, game_period_map={"401999999": 8}))

    def test_espn_fallback_wrong_period_in_map(self):
        """ESPN PP flag ignored if the player's PROBABLE game is mapped to a different period."""
        e = self._add_espn_probable(make_sp("Gerrit Cole", pro_team_id=5))
        # game_period_map says game 401999999 is on period 9, not 8
        self.assertFalse(el.has_start(e, 8, {}, game_period_map={"401999999": 9}))

    def test_espn_fallback_not_used_when_mlb_has_data(self):
        """ESPN PP flag does not fire when MLB Stats API has data for the period."""
        e = self._add_espn_probable(make_sp("Gerrit Cole", pro_team_id=5))
        # MLB has starters for period 8, but Gerrit Cole is not among them
        self.assertFalse(el.has_start(e, 8, {8: {"shane bieber"}},
                                      game_period_map={"401999999": 8}))

    def test_espn_fallback_empty_map(self):
        """ESPN PP flag not used when game_period_map is empty (view unavailable)."""
        e = self._add_espn_probable(make_sp("Gerrit Cole", pro_team_id=5))
        self.assertFalse(el.has_start(e, 8, {}, game_period_map={}))


# ── TestOptimizePitchers ──────────────────────────────────────────────────────

class TestOptimizePitchers(unittest.TestCase):

    def _moves_map(self, moves):
        """Return {playerName: (fromSlot, toSlot)} for easier assertion."""
        return {
            m["playerName"]: (m["fromLineupSlotId"], m["toLineupSlotId"])
            for m in moves
        }

    def test_no_changes_needed(self):
        """All starting SPs already in SP slots — no moves."""
        entries = [
            make_sp("Cole",   slot=el.SLOT_SP, pro_team_id=10),
            make_sp("Bieber", slot=el.SLOT_SP, pro_team_id=2),
        ]
        prob = {1: {"cole", "bieber"}}
        moves, skipped, no_slot = el.optimize_pitchers(
            entries, 1, probable_starters=prob,
            slot_counts=make_slot_counts(sp=2, rp=0, p=0),
        )
        self.assertEqual(moves, [])
        self.assertEqual(skipped, [])
        self.assertEqual(no_slot, [])

    def test_benched_sp_promoted_to_free_slot(self):
        """A starting SP on the bench should move to a free SP slot."""
        entries = [
            make_sp("Cole", slot=el.SLOT_BE, pro_team_id=10),
        ]
        prob = {1: {"cole"}}
        moves, _, _ = el.optimize_pitchers(
            entries, 1, probable_starters=prob,
            slot_counts=make_slot_counts(sp=1, rp=0, p=0),
        )
        m = self._moves_map(moves)
        self.assertIn("Cole", m)
        self.assertEqual(m["Cole"], (el.SLOT_BE, el.SLOT_SP))

    def test_starting_sp_displaces_resting_sp(self):
        """A starting SP on the bench displaces a resting SP to claim its slot."""
        entries = [
            make_sp("Starter", slot=el.SLOT_BE, pro_team_id=10),  # has start
            make_sp("Rester",  slot=el.SLOT_SP, pro_team_id=2),   # no start
        ]
        prob = {1: {"starter"}}
        moves, _, _ = el.optimize_pitchers(
            entries, 1, probable_starters=prob,
            slot_counts=make_slot_counts(sp=1, rp=0, p=0),
        )
        m = self._moves_map(moves)
        self.assertEqual(m.get("Starter"), (el.SLOT_BE, el.SLOT_SP))
        self.assertEqual(m.get("Rester"),  (el.SLOT_SP, el.SLOT_BE))

    def test_resting_sp_stays_put_when_slot_available(self):
        """A resting SP in an SP slot with no competing starting SP stays put."""
        entries = [
            make_sp("Rester", slot=el.SLOT_SP, pro_team_id=2),
        ]
        moves, _, _ = el.optimize_pitchers(
            entries, 1, probable_starters={1: set()},
            slot_counts=make_slot_counts(sp=1, rp=0, p=0),
        )
        self.assertEqual(moves, [])

    def test_il_players_untouched(self):
        """IL players should never appear in the move list."""
        entries = [
            make_sp("Cole", slot=el.SLOT_IL, pro_team_id=10),
        ]
        prob = {1: {"cole"}}
        moves, _, _ = el.optimize_pitchers(
            entries, 1, probable_starters=prob,
            slot_counts=make_slot_counts(sp=1, rp=0, p=0),
        )
        self.assertEqual(moves, [])

    def test_sp_threshold_benches_overflow(self):
        """When SPs starting >= SP_START_THRESHOLD, extras are benched."""
        entries = []
        prob_names = set()
        for i in range(el.SP_START_THRESHOLD + 1):
            name = f"SP{i}"
            entries.append(make_sp(name, slot=el.SLOT_SP, pro_team_id=i + 1))
            prob_names.add(name.lower())
        prob = {1: prob_names}
        slot_c = make_slot_counts(sp=el.SP_START_THRESHOLD + 1, rp=0, p=0)
        moves, skipped, _ = el.optimize_pitchers(
            entries, 1, probable_starters=prob, slot_counts=slot_c,
        )
        self.assertEqual(len(skipped), 1)
        benched = [m for m in moves if m["toLineupSlotId"] == el.SLOT_BE]
        self.assertEqual(len(benched), 1)

    def test_rp_placed_in_p_slot(self):
        """An RP on the bench moves to the generic P slot (RPs are not eligible for the RP slot)."""
        # ESPN "RPs" (true relievers) are eligible for SP(13) and P(15) only — not RP(14).
        # The fantasy RP slot (14) is reserved for SPs playing in a relief role.
        entries = [
            make_rp("Clase", slot=el.SLOT_BE, pro_team_id=5),
        ]
        moves, _, no_slot = el.optimize_pitchers(
            entries, 1, probable_starters={},
            slot_counts=make_slot_counts(sp=0, rp=0, p=1),
        )
        m = self._moves_map(moves)
        self.assertIn("Clase", m)
        self.assertEqual(m["Clase"][1], el.SLOT_P)
        self.assertEqual(no_slot, [])

    def test_no_slot_benched_and_reported(self):
        """When all active slots are full, overflow SPs end up in no_slot and get benched."""
        # 2 starting SPs, only 1 SP slot, no P slot
        entries = [
            make_sp("A", slot=el.SLOT_SP, pro_team_id=10),
            make_sp("B", slot=el.SLOT_SP, pro_team_id=2),
        ]
        prob = {1: {"a", "b"}}
        moves, _, no_slot = el.optimize_pitchers(
            entries, 1, probable_starters=prob,
            slot_counts=make_slot_counts(sp=1, rp=0, p=0),
        )
        self.assertEqual(len(no_slot), 1)
        benched = [m for m in moves if m["toLineupSlotId"] == el.SLOT_BE]
        self.assertEqual(len(benched), 1)

    def test_rp_falls_back_to_sp_slot(self):
        """When no P slot is available, an RP falls back to an SP slot."""
        entries = [
            make_rp("Clase", slot=el.SLOT_BE, pro_team_id=5),
        ]
        moves, _, no_slot = el.optimize_pitchers(
            entries, 1, probable_starters={},
            slot_counts=make_slot_counts(sp=1, rp=0, p=0),
        )
        m = self._moves_map(moves)
        self.assertIn("Clase", m)
        self.assertEqual(m["Clase"][1], el.SLOT_SP)
        self.assertEqual(no_slot, [])


if __name__ == "__main__":
    unittest.main()
