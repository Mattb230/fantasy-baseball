# Fantasy Baseball ESPN Automation

Scripts to automate ESPN Fantasy Baseball lineup management and player data pulls.

## Scripts

| File | Purpose |
|---|---|
| `espn_lineup.py` | **Primary optimizer.** Manages pitcher lineup slots for today and future days using MLB Stats API for probable starters. |
| `espn_roster.py` | Older/simpler pitcher optimizer. Uses ESPN's embedded game schedule data rather than MLB Stats API. |
| `espn_players.py` | Pulls all players + stats to a dated JSON file (`players_YYYY-MM-DD.json`). |

## Running

```bash
python espn_lineup.py                  # today only, live
python espn_lineup.py --dry-run        # preview without submitting
python espn_lineup.py --days 3         # today + 2 more days
python espn_lineup.py --debug          # dump raw JSON to debug_*.json

python espn_players.py                 # interactive: pulls all players to JSON
python espn_roster.py                  # interactive: older roster optimizer
```

## Configuration

- **League ID:** 176349
- **Season:** 2026
- **Team ID:** 5 (BONR)

### Credentials (ESPN_S2 + SWID)

Credentials can be set two ways (env vars take priority):
1. Hardcoded at the top of each script (avoid committing real values)
2. Environment variables: `ESPN_S2` and `SWID`

> **Security note:** `espn_lineup.py` currently has real credentials hardcoded. These should be moved to environment variables or a `.env` file (add `.env` to `.gitignore`).

## Architecture

- **ESPN private API** — authenticated via browser cookie pair (`espn_s2` + `SWID`)
  - Read endpoint: `lm-api-reads.fantasy.espn.com/apis/v3/games/flb/...`
  - Write endpoint: `fantasy.espn.com/apis/v3/games/flb/...`
- **MLB Stats API** (`statsapi.mlb.com`) — public, no auth; used for game schedules and probable starters
- `ESPN_TO_MLB_TEAM` / `MLB_TO_ESPN_TEAM` in `espn_lineup.py` maps between the two team ID systems

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
3. SPs not starting → keep current slot unless displaced; bench only if needed
4. If 9+ SPs scheduled on one day → bench lowest-priority ones with a warning

## Important Constraints

- Never touch IL players
- SP slots → SP-eligible only; RP slots → RP-eligible only; P slot → either
- `espn_roster.py` and `espn_lineup.py` have diverged — `espn_lineup.py` is the maintained version
- Debug JSON files (`debug_*.json`) are not committed to git
