# Requirements Traceability

This page maps every requirement in the challenge brief and the submission guidelines to where it is met, the evidence for it, and its status. Evidence links point to tests and to measured results in [TEST_RESULTS.md](TEST_RESULTS.md).

Status key: ✅ met, with evidence · ⚠️ met, but with a stated limit · ⏳ still to be done by the candidate

## Submission deliverables

| # | Deliverable | Location | Status |
|---|---|---|---|
| D1 | System design document, with all Part 1 sections | [DESIGN.md](DESIGN.md) | ✅ |
| D2 | AI collaboration in design | [DESIGN.md §14](DESIGN.md#14-ai-collaboration-in-design), plus the design table in [AI_COLLABORATION.md](AI_COLLABORATION.md) | ✅ |
| D3 | Working code for the implemented component | `quiz_server/` | ✅ |
| D4 | Documentation and comments on AI collaboration in implementation | An `AI-ASSISTED` note at the top of each module, plus [AI_COLLABORATION.md](AI_COLLABORATION.md) | ✅ |
| D5 | Code that considers scalability, performance and the other qualities | See P1 to P5 below | ✅ |
| D6 | Instructions to run the code and tests | [README.md](../README.md), "Quick start" and "Verification" | ✅ |
| D7 | Video, 5 to 10 minutes | Not in the repository | ⏳ Candidate records it |
| D8 | The candidate's own verification, in their words | [AI_COLLABORATION.md](AI_COLLABORATION.md), "Candidate's own review and testing" | ⏳ A draft exists; the candidate must confirm and edit it |

## Part 1: System design

| # | Requirement | Where | Status |
|---|---|---|---|
| S1 | Architecture diagram showing server, clients, database and the real-time layer | [architecture.svg](architecture.svg) and [architecture.png](architecture.png), plus a Mermaid version in DESIGN.md §2 | ✅ |
| S2 | Description of each component's role | DESIGN.md §3 | ✅ |
| S3 | Data flow from joining a quiz to the leaderboard update | DESIGN.md §4: a sequence diagram and six steps. The diagram also has a data-flow strip. | ✅ |
| S4 | Technologies and tools, with justification | DESIGN.md §6: choice, reason and alternatives for each component | ✅ |

## Part 2: Implementation

| # | Requirement | How it is met | Evidence | Status |
|---|---|---|---|---|
| I1 | Pick one core real-time component and mock the rest | Real-time Quiz Service implemented. Auth, quiz content and the client are mocked. | DESIGN.md §1 | ✅ |
| I2 | Join a quiz session with a unique quiz ID | `/ws/quizzes/{quiz_id}`. `POST /api/quizzes` issues random 8-character IDs. Unknown IDs are rejected with close code 4404. | `test_join_…`, `test_unknown_quiz_is_rejected`, `test_created_quiz_can_be_joined_by_id` | ✅ |
| I3 | Many users join the same session at once | Per-quiz connection registry, with shared state in the store | `test_other_players_see_leaderboard_update`; the load test with 1,000 players in one quiz | ✅ |
| I4 | Scores update in real time as answers arrive | `answer_result` with the new total is sent right after scoring | `test_correct_answer_scores_…`; load test round trip p50 0.6 ms at 1,000 players | ✅ |
| I5 | Scoring is accurate and consistent | Server-side timer and scoring. One atomic dedupe-and-increment step. | Concurrency contract tests on both stores; 0 score mismatches in every load test; mutation check 8 of 8 | ✅ |
| I6 | Leaderboard shows everyone's standings in real time | Top 10 plus the player's own rank and the total player count, pushed at most every 100 ms | `test_other_players_…`, `test_leaderboard_versions_never_go_backwards`; leaderboard latency p50 87 to 118 ms | ✅ (see note) |
| I7 | Leaderboard updates promptly | Coalesced pushes, versioned snapshots | As I6 | ✅ |

**Note on I6.** Clients receive the top 10 and their own rank, not every participant. The REST endpoint returns up to 100 entries. This is a deliberate trade-off for payload size, explained in DESIGN.md §7.

## AI collaboration in implementation

| # | Requirement | Where | Status |
|---|---|---|---|
| A1 | Mark the code sections generated or significantly helped by AI | An `AI-ASSISTED` note at the top of every non-trivial module, test file, script and the demo page. Empty package files and `conftest.py` have none. | ✅ |
| A2 | The tool and the task | AI_COLLABORATION.md, "Tool and working style" and "Implementation phase" | ✅ |
| A3 | The prompts, or the nature of the interaction | AI_COLLABORATION.md: the initial prompt, and the follow-up prompts in the candidate section | ✅ |
| A4 | Steps taken to verify, test, debug and refine the AI's output (mandatory) | AI_COLLABORATION.md: 9 issues found and fixed, the mutation results and known limits. TEST_RESULTS.md holds the raw evidence. | ✅ AI side · ⏳ candidate's own review (D8) |

## Build for the future

| # | Requirement | Design | Implementation and evidence | Status |
|---|---|---|---|---|
| P1 | Scalability, with trade-offs discussed | DESIGN.md §7 | Stateless nodes, a Redis store keyed by `{quiz_id}` hash tags, and per-quiz pub/sub. The two-node test passes. | ⚠️ Multi-node tested only in-process against fakeredis. Measured up to 4,000 players on one process. |
| P2 | Performance under heavy load | DESIGN.md §8 | Coalesced fan-out, JSON encoded once per push, pipelined reads. About 20 µs of server processing per answer. | ⚠️ One process on this laptop saturates at 2,000 to 4,000 active players (TEST_RESULTS.md §4) |
| P3 | Reliability and graceful error handling | DESIGN.md §9 | Idempotent answers, reconnect-and-resume, bounded queues, validation, size and rate limits. Tests exist for each of these. | ⚠️ Some failure paths are implemented but untested (TEST_RESULTS.md §6) |
| P4 | Maintainability | DESIGN.md §11 | Modules with one job each, abstract store and bus interfaces, one contract suite for both stores, dependency injection, a typed protocol, and Make targets | ✅ |
| P5 | Monitoring and observability | DESIGN.md §10 | `/metrics` with 10 metric families, JSON logs, `/healthz` and `/readyz` | ✅ Metrics endpoint tested. Dashboards, alerts and tracing are designed only. |
