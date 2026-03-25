# Fantasy Baseball ESPN Automation

Scripts to automate ESPN Fantasy Baseball lineup management and player data pulls.

## Scripts

| File | Purpose |
|---|---|
| `espn_lineup.py` | **Primary optimizer.** Manages pitcher lineup slots for today and future days using MLB Stats API for probable starters. |
| `espn_players.py` | Pulls all players + stats to a dated JSON file (`players_YYYY-MM-DD.json`). |
| `espn_roster.py` | Older/simpler pitcher optimizer. Uses ESPN's embedded game schedule data rather than MLB Stats API. |
| `test_espn_lineup.py` | Unit tests for optimizer logic (role detection, start detection, move generation, schedule calibration). |

## Running

```bash
python espn_lineup.py                  # today only, live
python espn_lineup.py --dry-run        # preview without submitting
python espn_lineup.py --days 3         # today + 2 more days
python espn_lineup.py --debug          # dump raw JSON to debug_*.json

python -m pytest test_espn_lineup.py -v   # run optimizer unit tests

python espn_players.py                 # interactive: pulls all players to JSON
python espn_roster.py                  # interactive: older roster optimizer
```

## Configuration

- **League ID:** 176349
- **Season:** 2026
- **Team ID:** 5 (BONR)

### Credentials (ESPN_S2 + SWID)

Credentials are loaded from a `.env` file or environment variables (env vars take priority).
Copy `.env.example` to `.env` and fill in your values.

```
ESPN_S2=your_espn_s2_value
SWID={your-swid-guid}
```

## Architecture

- **ESPN private API** — authenticated via browser cookie pair (`espn_s2` + `SWID`)
  - Read endpoint: `lm-api-reads.fantasy.espn.com/apis/v3/games/flb/...`
  - Write endpoint: `lm-api-writes.fantasy.espn.com/apis/v3/games/flb/...`
- **MLB Stats API** (`statsapi.mlb.com`) — public, no auth; used for game schedules and probable starters
- `ESPN_TO_MLB_TEAM` / `MLB_TO_ESPN_TEAM` in `espn_lineup.py` maps between the two team ID systems

### ESPN Write API notes

- All POST requests require `?platformVersion=<build-hash>` as a query param.
  The hash is stored in `ESPN_PLATFORM_VERSION` at the top of `espn_lineup.py`.
  Update it if transactions start returning 400 errors (capture from browser DevTools).
- **Transaction type** varies by period:
  - Current period → `"type": "LINEUP_ADJUSTMENT"`
  - Future periods → `"type": "FUTURE_ROSTER"` plus `"memberId"` (= SWID) and `"executionType": "EXECUTE"`
- Required item fields: `fromLineupSlotId`, `fromTeamId` (0), `isKeeper` (false), `overallPickNumber` (0), `playerId`, `toLineupSlotId`, `type` ("LINEUP")

## Lineup Slot IDs

| ID | Slot |
|---|---|
| 13 | SP |
| 14 | RP |
| 15 | P (generic — accepts SP or RP) |
| 16 | BE (bench) |
| 17 | IL |

## Optimizer Priority Rules (espn_lineup.py)

1. RPs → always in an active slot (RP slot first, then P)
2. SPs with a probable start → active slot (SP first, then P)
3. SPs not starting → stay in their current slot unless displaced by a higher-priority player
4. If 9+ SPs scheduled on one day → bench lowest-priority ones with a warning

## Important Constraints

- Never touch IL players
- SP slots → SP-eligible only; RP slots → RP-eligible only; P slot → either
- `espn_roster.py` and `espn_lineup.py` have diverged — `espn_lineup.py` is the maintained version
- Debug JSON files (`debug_*.json`) are not committed to git
