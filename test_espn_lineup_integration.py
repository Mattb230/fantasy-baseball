"""
Integration tests for espn_lineup.py — require ESPN credentials and network access.

Run with:
    python -m pytest test_espn_lineup_integration.py -v

Skips automatically if ESPN_S2 / SWID environment variables are not set.
No changes are submitted to ESPN.
"""
import copy
import datetime
import unittest

import espn_lineup as el


class TestIntegration(unittest.TestCase):

    def test_benched_pitchers_get_activated(self):
        """
        Fetch a real future roster, bench active starting SPs and RPs in memory,
        then verify the optimizer generates moves to activate them.

        Uses the first future scoring period that has probable starters on the roster.
        No changes are submitted to ESPN.
        """
        if not el.ESPN_S2 or not el.SWID:
            self.skipTest("ESPN credentials not set (ESPN_S2 / SWID env vars missing)")

        session = el.get_session()
        today_period, latest_period, slot_counts = el.get_league_info(session)

        base_date = datetime.date.today()
        schedule, probable_starters, base_date = el.build_schedule_lookup(
            today_period, base_date, num_days=7
        )

        # Find the first future period that has probable starters on this roster
        target_period = None
        target_entries = None
        for day_offset in range(1, 8):
            period = today_period + day_offset
            entries = el.get_roster(session, period)
            non_il = [e for e in entries if el.current_slot(e) != el.SLOT_IL]
            has_starting_sp = any(
                el.is_sp(e) and el.has_start(e, period, probable_starters)
                for e in non_il
            )
            if has_starting_sp:
                target_period = period
                target_entries = entries
                break

        if target_period is None:
            self.skipTest("No probable starters found on roster in the next 7 days")

        # Deep-copy entries and bench all active starting SPs and RPs
        modified = copy.deepcopy(target_entries)
        benched = []
        for e in modified:
            if el.current_slot(e) == el.SLOT_IL:
                continue
            if el.current_slot(e) != el.SLOT_BE:
                if (el.is_sp(e) and el.has_start(e, target_period, probable_starters)) \
                        or el.is_rp(e):
                    benched.append(el.player_name(e))
                    e["lineupSlotId"] = el.SLOT_BE

        if not benched:
            self.skipTest("No active starting SPs or RPs to bench for target period")

        moves, _, no_slot = el.optimize_pitchers(
            modified, target_period, schedule, probable_starters, slot_counts
        )
        moves_map = {m["playerName"]: m["toLineupSlotId"] for m in moves}

        for name in benched:
            self.assertIn(name, moves_map,
                          f"{name} was benched but optimizer did not generate a move for them")
            self.assertNotEqual(moves_map[name], el.SLOT_BE,
                                f"{name} was moved but destination is still the bench")

        self.assertEqual(no_slot, [],
                         f"Optimizer could not find active slots for: "
                         f"{[el.player_name(e) for e in no_slot]}")


if __name__ == "__main__":
    unittest.main()
