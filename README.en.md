# FeltLedger · Live Hand Recorder and Poker Strategy Research

English · [中文](README.md)

FeltLedger is a prototype for **academic research, rule verification, and non-monetary experiments** involving no-limit Texas hold'em. People shuffle and deal a fresh hand at the table; the software records only the cards, actions, and payouts entered. It does not deal cards, take deposits, allow withdrawals or cash conversion, or arrange games. This release is a single-user local prototype. It requires Python 3.10+ and has no third-party dependencies.

## Run and use

```powershell
python app.py
```

Open <http://127.0.0.1:8765/>. The server listens only on `127.0.0.1`.

1. Set 2–9 seats, the button, your seat, blinds, optional ante, and **total table chips**. Distribute the total evenly or edit each stack; the stack sum must match the table total.
2. Record the current player's actual action in turn: fold, check, call, raise to a total amount, or all-in. The table shows current-street bets, pot, stacks, and legal raise limits. Enter three new cards on the flop and one each on the turn and river. Opponents can act on every betting street.
3. Enter only hole cards you actually know; unknown cards stay hidden. Click an opponent's seat name, such as “对手5”, to select a previously saved real-world opponent or create a new name, style, and note. The association carries into the next hand. When you meet that player in another session, select and edit the same profile again.
4. The hand ends immediately when only one player remains. At showdown, the app can rank known hands and distribute side pots if every remaining hand is known. Otherwise, enter the actual payouts observed at the table. Manual payouts are checked for their total only; side-pot eligibility is not verified.
5. “Next hand” archives the completed hand, moves the button, posts blinds again, and clears all cards. Shuffle and deal the next hand at the real table. “Undo” restores only the latest current-hand operation.

The current hand and one-step undo are stored in `data/current_game.json` and `data/undo.json`; opponent profiles are in `data/profiles.json`. Clicking “Next hand” immediately archives the completed hand in `data/archive.sqlite3`. The UI loads ten archive summaries per page, with an option to inspect one hand. Git ignores these data files. Resetting the table overwrites an unfinished hand after a confirmation prompt.

## Project and use boundaries

- The code and documentation use the [PolyForm Noncommercial License 1.0.0](LICENSE). Noncommercial research, study, and experiments are covered by its terms. **Commercial use, resale, paid services, or other profit-making use require the copyright holder's prior express written permission.** The license restricts commercial use, so this is *source-available* software, not OSI-defined open source.
- Real hand histories, player names, and profiles in `data/` are not part of the published repository. The software license does not grant permission to share or train on that data. Do not commit this directory, credentials, or identifying information.
- The current scope is manual recording at a real table and research review. Check each online platform's current rules before any integration. Do not use this project for prohibited real-time assistance or to mine hands you did not play.
- Experimental estimates are for non-monetary experiments and offline analysis only. **Do not use them for real-money hands or real-time decisions on online platforms.** Research labeling alone does not determine the legal status of a particular use or override platform rules.
- Current advice offers no profit guarantee. Strategy accuracy, competitive performance, and special game variants have not been validated.

## Database and future deployment boundary

The layers are `game.py` for rules, `policy.py` for the current player's visible `PolicyInput-v1`, and `storage.py` for archived hands. The SQLite `hands` table deduplicates on `hand_id`, pages by increasing `sequence`, and stores archive time, player count, total chips, result method, and a full JSON snapshot. Each completed hand is committed immediately rather than collected in an unbounded JSONL file. SQLite WAL uses automatic checkpoints. Future offline training can stream batches with `storage.iter_hands(batch_size=...)`.

If an older `data/hands.jsonl` exists, startup imports it line by line in transactions of 100 hands and renames the source to `hands.jsonl.migrated` as a backup after success. An interrupted import can be retried without duplicate hand IDs. Back up `data/` before migration. Set `FELTLEDGER_DATA_DIR` to place private data outside the project folder.

`GET /api/hands?limit=10&before=<sequence>` returns archive summaries; `GET /api/hands/<hand_id>` returns one hand; `GET /api/game/observation` returns a versioned current-decision observation when it is your seat's turn. The observation excludes opponents' hidden cards and private notes. Future models should consume this boundary. The [model plan](模型训练与数据适配方案.md) documents input/output versions and integer-cent amounts.

**The server still binds only to `127.0.0.1`. It has no accounts, access controls, or multi-user isolation and must not be exposed directly to the Internet.** A future hosted service should add authentication, user and hand isolation, backup, access audit, and data deletion, and can replace SQLite with a server database while retaining the rules and observation contract. Set performance targets after measuring real data volumes and concurrency.

Proposed hosted schema: `users(id)` owns `sessions(id, owner_id, ruleset_version)` and `profiles(id, owner_id, ...)`; `hands(id, session_id, sequence, archived_at, summary, snapshot_json)` is paged within a session with a unique `(session_id, id)` constraint. Add a derived `hand_actions(hand_id, ordinal, street, seat, action, amount_cents)` table only if training queries need per-action indexing. Preserve original snapshots, ruleset versions, and provenance during migration; the current single-user IDs are not cross-user identities.

## Standard hand-flow comparison

| Real-table step | Current behavior |
|---|---|
| Shuffle, deal two hole cards, post blinds/ante | Cards are dealt in person. The app posts blinds/ante and records only known hole cards; the button posts the small blind heads-up. |
| Preflop action | The first player left of the big blind acts first; the button acts first heads-up. |
| Flop, turn, river | Enter 3, 1, and 1 new board cards; the first active player left of the button acts first on each street. |
| Betting | Record fold, check, call, raise-to, and all-in in turn; validate minimum raises and betting rights after a short all-in. |
| Uncalled bets, fold win, showdown | Return uncalled amounts; support wins by fold, hand ranking, ties, side pots, and manually entered payouts. |
| Next hand | Move the button among seats with chips, clear old cards, and reshuffle at the table. |

Rules references: [PokerStars poker rules](https://www.pokerstars.com/poker/games/rules/) and [betting and side-pot rules](https://www.pokerstars.com/help/articles/poker-rules-master/229146/). The MVP covers ordinary no-limit hold'em. Rake, straddles, insurance, multiple runouts, squid variants, and mid-session buy-ins or seat changes need separate rules.

## Comparable tools and layout

| Reference | Useful pattern | FeltLedger |
|---|---|---|
| [binked](https://binked.app/) | Live, street-by-street recording of players, blinds, stacks, and actions | Table seats, action controls, and street history |
| [PokerTracker 4 Replayer](https://docs.pokertracker.com/pt4/tutorials/hand-analysis-and-tools/replayer/) | Review the pot, stacks, and action sequence | Fact display and action history; no step-by-step replay control yet |
| [HandRecorder](https://apps.apple.com/us/app/handrecorder-poker-tracker/id6751004127) | Manual recording for later hand review | Local JSONL archive and opponent profiles reused across sessions |

The table, pot, board, action buttons, and history share one screen to make live entry easier. This comparison defines interaction scope; it is not a claim of equivalent features or performance.

## Facts, estimates, and model research

See the [model training and data adaptation plan](模型训练与数据适配方案.md) for the current and proposed input/output contracts, unlabeled-data use, candidate frameworks, data sources, adversarial self-play, staged evaluation, and cost estimates. The plan has a version and update log. **No model training has started.**

- **Facts:** Entered cards and actions, plus the pot, stacks, legal actions, and best known five-card hands calculated from them. Incorrect entry produces incorrect facts; check them against the table.
- **Estimates:** When it is your turn and your hole cards are known, the app shows showdown equity from 1,500 samples of random unknown opponent hands, a sampling interval, and a simplified call estimate. A manually selected opponent style only adjusts the suggestion threshold; it does not model that player's real hand range.
- **Unmeasured:** Strategy accuracy, real action EV, profitability, and competitive performance. The sampling interval describes simulation noise, not decision accuracy. Current suggestions are neither a trained RL policy nor a GTO solution.

To evaluate future model performance, fix the rules, blinds, stack depths, opponent pool, and held-out seeds; then compare net results per 100 hands, uncertainty, latency, and model versions in blind tests. `poker.advise()` is the current integration point for a future policy.

## Verify

```powershell
python -m unittest discover -s tests -v
```

Tests cover common hand-ranking cases, heads-up order, betting on every street, short all-ins, side pots, duplicate cards, total-chip checks, and profiles reused across hands. Real hands still require comparison with what happened at the table.
