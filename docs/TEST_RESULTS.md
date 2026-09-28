# Test Results

Every result on this page was produced by running the commands shown, on the author's machine. Nothing here is estimated.

**Environment:** Apple M1 Pro with 8 cores, macOS, Python 3.14.7. One uvicorn process with the in-memory store. The load generator ran on the same machine.

**Primary run:** 2026-09-28. The 4,000-player figures in section 4 come from an earlier run on 2026-09-25, with the same code except for later changes to the browser page.

## 1. Automated tests

```bash
make test        # .venv/bin/python -m pytest -q --timeout 30
```

**Result: 50 passed in 1.78 s.** The whole suite was then run 10 more times in a row, and it passed all 10 times.

**Clean install from the submission zip.** `make package` was run, the zip was extracted to an empty folder, and `make install` then `make test` were run there with a new virtual environment. **Result: 50 passed in 3.30 s.**

| File | Tests | What it covers |
|---|---|---|
| `test_scoring.py` | 8 | Scoring rule: 7 boundary cases, plus "faster never scores less" |
| `test_store_contract.py` | 18 | The same 9 behaviours run against the in-memory store **and** the Redis store (fakeredis with real Lua) |
| `test_ws.py` | 19 | End to end through the real WebSocket endpoint |
| `test_hub.py` | 4 | Leaderboard coalescing, slow client, stuck client, unsubscribe |
| `test_multinode.py` | 1 | Two server nodes sharing one Redis |

Test names by requirement:

| Requirement | Tests |
|---|---|
| Join by unique quiz ID | `test_join_returns_state_first_question_and_leaderboard`, `test_unknown_quiz_is_rejected`, `test_invalid_user_id_is_rejected` (4 cases), `test_created_quiz_can_be_joined_by_id` |
| Real-time score updates | `test_correct_answer_scores_with_server_side_speed_bonus`, `test_wrong_late_and_skipped_answers_score_zero`, `test_full_quiz_ends_with_quiz_complete` |
| Accurate, consistent scoring | `test_record_answer_adds_points_once`, `test_concurrent_duplicate_submissions_count_once`, `test_concurrent_answers_from_many_users_are_all_counted`, `test_duplicate_answer_is_not_double_counted`, `test_cannot_answer_a_question_before_it_is_served`, `test_mark_served_keeps_first_timestamp`, `test_score_answer`, `test_faster_never_scores_less` |
| Real-time leaderboard | `test_other_players_see_leaderboard_update`, `test_leaderboard_versions_never_go_backwards`, `test_leaderboard_order_and_tiebreak`, `test_burst_of_answers_is_coalesced_into_few_snapshots` |
| Multiple nodes | `test_score_on_node_b_reaches_leaderboard_on_node_a` |
| Reliability | `test_reconnect_resumes_score_and_keeps_question_timer`, `test_invalid_messages_do_not_drop_the_connection`, `test_oversized_message_closes_with_1009`, `test_rate_limit`, `test_slow_client_gets_latest_snapshot_only`, `test_stuck_client_is_disconnected_and_memory_is_bounded` |
| Store behaviour | `test_add_participant_is_idempotent`, `test_version_increases_on_every_change`, `test_quizzes_are_isolated`, `test_unknown_quiz_is_empty`, `test_unregister_last_connection_unsubscribes` |
| Observability endpoints | `test_rest_leaderboard_health_and_metrics` |

## 2. Mutation check

This check proves the tests actually protect the critical rules. It breaks one behaviour at a time and confirms the suite fails.

```bash
make mutation    # .venv/bin/python scripts/mutation_check.py
```

**Result: 8 of 8 mutants caught.**

```
CAUGHT  | redis Lua dedupe removed             | FAILED tests/test_store_contract.py::test_record_answer_adds_points_once[redis]
CAUGHT  | memory dedupe removed                | FAILED tests/test_store_contract.py::test_record_answer_adds_points_once[memory]
CAUGHT  | served timer resets on reconnect     | FAILED tests/test_store_contract.py::test_mark_served_keeps_first_timestamp[memory]
CAUGHT  | coalescing window removed            | FAILED tests/test_hub.py::test_burst_of_answers_is_coalesced_into_few_snapshots
CAUGHT  | leaderboard order reversed in redis  | FAILED tests/test_multinode.py::test_score_on_node_b_reaches_leaderboard_on_node_a
CAUGHT  | not-served check removed             | FAILED tests/test_ws.py::test_cannot_answer_a_question_before_it_is_served
CAUGHT  | bus publish skipped                  | FAILED tests/test_hub.py::test_burst_of_answers_is_coalesced_into_few_snapshots
CAUGHT  | server-side elapsed time ignored     | FAILED tests/test_ws.py::test_correct_answer_scores_with_server_side_speed_bonus
```

The first version of this check, on 2026-09-25, found two problems in the test suite itself. One mutant survived, and three hung instead of failing. Both problems are described in [AI_COLLABORATION.md](AI_COLLABORATION.md), issues 4 and 5.

## 3. Load test (primary run, 2026-09-28)

```bash
make run                                     # terminal 1
.venv/bin/python scripts/load_test.py \
    --quizzes 20 --players 50 --think-ms 500 # terminal 2, and so on for each row
```

Every simulated player joins, answers all 5 questions with a random choice after a random think time, and records two timings:
- **Answer round trip:** from sending the answer to receiving the result.
- **Leaderboard latency:** from sending the answer to receiving the first leaderboard snapshot that includes it.

At the end the script cross-checks every player's final score against the points the server reported, and checks the REST leaderboard's player count.

| Scenario | Arguments | Answers/s | Round trip p50 / p95 / p99 | Leaderboard latency p50 / p95 / p99 | Leaderboard messages (naive design) | Failed connects | Score mismatches |
|---|---|---|---|---|---|---|---|
| 20 quizzes × 50 players | `--think-ms 500` | 1,650 | 0.6 / 35.4 / 47.0 ms | 87.2 / 149.0 / 164.2 ms | 11,631 (250,000) | 0 | 0 |
| 1 quiz × 1,000 players | `--think-ms 1000` | 917 | 0.6 / 40.4 / 216.2 ms | 89.8 / 152.1 / 232.7 ms | 21,706 (5,000,000) | 0 | 0 |
| 20 quizzes × 100 players | `--think-ms 2000 --ramp-s 3` | 797 | 5.8 / 94.8 / 133.8 ms | 118.2 / 241.5 / 306.7 ms | 78,193 (1,000,000) | 0 | 0 |

Across all three runs:
- There were 0 protocol errors, and the REST player totals agreed every time.
- The server log contained 0 error lines.
- The server recorded 20,000 answers: 5,005 correct and 14,995 incorrect.
- Server-side answer processing totalled 0.393 s for those 20,000 answers, about 20 µs each. The rest of the round trip is network, framing and CPU queueing.
- The server recorded 0 slow-consumer disconnects.

"Naive design" means one leaderboard push to every player in the quiz for every answer, which is answers × players per quiz.

## 4. Load test at saturation (earlier run, 2026-09-25)

| Scenario | Arguments | Answers/s | Round trip p50 / p99 | Leaderboard latency p50 / p99 | Failed connects | Score mismatches |
|---|---|---|---|---|---|---|
| 40 quizzes × 100 players | `--think-ms 2000 --ramp-s 5` | 903 | 197.8 / 659.1 ms | 402.5 / 1,036.3 ms | 31 of 4,000 | 0 among completed players |

- This scenario was run three times. The table shows the third run, which used a 5-second connection ramp-up.
  - The first run, with no ramp-up, completed all 4,000 players with 0 failed connects: answer round trip p50 263 ms and p99 689 ms, and 0 score mismatches.
  - The second and third runs each had 31 failed connects.
- During the second run, with no ramp-up, the CPU of both processes was sampled once a second for 12 seconds. After start-up, the server ran at about 50 to 87% of one core. The load generator ran at about 20 to 86%, mostly above 70%. The laptop was saturated, so latency here reflects CPU contention.
- The cause of the failed connects was **not confirmed**. The macOS listen backlog was 128 (`kern.ipc.somaxconn`), and about 4,000 sockets from earlier runs were in TIME_WAIT at the time. Both are plausible causes.

## 5. Manual testing in the browser

Done by the candidate on the first version of the demo page:
- Played the full demo quiz as one player and reached the finish screen with 577 points.
- Tested two windows. This found that both windows were the same player, because the player ID was stored in `localStorage`. The fix stores it per tab in `sessionStorage`.

The redesigned page was checked only for JavaScript syntax, using JavaScriptCore. It still needs a two-tab check in a real browser.

## 6. Implemented but not covered by any automated test

These behaviours exist in the code and are described in the design, but no test exercises them:

| Behaviour | Code |
|---|---|
| Close code 1012 on graceful shutdown | `Hub.stop()` |
| `/readyz` returns 503 when the store is unreachable | `app.py` `readyz` |
| `internal_error` reply when the store fails during an answer | `app.py` WebSocket handler |
| Periodic 5-second resync after a lost pub/sub message | `Hub._flush_loop` |
| Local fallback when a bus publish fails | `Hub.notify_changed` |
| Redis pub/sub reader reconnect with back-off | `RedisBus._reader` |
| Client reconnect with back-off and jitter | `client/index.html` |
| Docker image, Compose file and nginx config | `Dockerfile`, `docker-compose.yml`, `deploy/nginx.conf`, never run |
| Redis store against a real Redis server | Only run against fakeredis |
