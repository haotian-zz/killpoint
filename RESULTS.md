Runs: 8466 (7968 with a crash, 498 baselines).

Validity checks: all passed.

### Outcome of crashed runs, deterministic model

| runtime | step granularity | key: none | key: args_hash | key: position | key: native | key: intent_log |
|---|---|---|---|---|---|---|
| temporal | per_call | duplicate 12/48 | ok 48/48 | ok 48/48 | ok 48/48 | ok 48/48 |
| temporal | per_batch | duplicate 15/48 | ok 48/48 | ok 48/48 | ok 48/48 | ok 48/48 |
| temporal | per_turn | duplicate 15/48 | ok 48/48 | ok 48/48 | ok 48/48 | ok 48/48 |
| dbos | per_call | duplicate 12/48 | ok 48/48 | ok 48/48 | ok 48/48 | ok 48/48 |
| dbos | per_batch | duplicate 15/48 | ok 48/48 | ok 48/48 | ok 48/48 | ok 48/48 |
| dbos | per_turn | duplicate 15/48 | ok 48/48 | ok 48/48 | ok 48/48 | ok 48/48 |
| restate | per_call | duplicate 12/48 | ok 48/48 | ok 48/48 | ok 48/48 | ok 48/48 |
| restate | per_batch | duplicate 15/48 | ok 48/48 | ok 48/48 | ok 48/48 | ok 48/48 |
| restate | per_turn | duplicate 15/48 | ok 48/48 | ok 48/48 | ok 48/48 | ok 48/48 |
| langgraph | per_call | duplicate 24/80 | ok 80/80 | ok 80/80 | ok 80/80 | ok 48/48 |
| langgraph | per_batch | duplicate 43/80 | ok 80/80 | ok 80/80 | duplicate 27/80 | ok 48/48 |
| langgraph | per_turn | duplicate 25/80 | ok 80/80 | ok 80/80 | ok 80/80 | ok 48/48 |
| langgraph_sync | per_call | duplicate 13/48 | ok 48/48 | ok 48/48 | ok 48/48 | ok 48/48 |
| langgraph_sync | per_batch | duplicate 15/48 | ok 48/48 | ok 48/48 | ok 48/48 | ok 48/48 |
| langgraph_sync | per_turn | duplicate 15/48 | ok 48/48 | ok 48/48 | ok 48/48 | ok 48/48 |

### Outcome of crashed runs, nondeterministic model

| runtime | step granularity | key: none | key: args_hash | key: position | key: native | key: intent_log |
|---|---|---|---|---|---|---|
| temporal | per_call | duplicate 12/48 | ok 48/48 | ok 48/48 | ok 48/48 | ok 48/48 |
| temporal | per_batch | duplicate 15/48 | ok 48/48 | ok 48/48 | ok 48/48 | ok 48/48 |
| temporal | per_turn | duplicate 15/48 | duplicate 15/48 | diverged 15/48 | diverged 15/48 | ok 48/48 |
| dbos | per_call | duplicate 12/48 | ok 48/48 | ok 48/48 | ok 48/48 | ok 48/48 |
| dbos | per_batch | duplicate 15/48 | ok 48/48 | ok 48/48 | ok 48/48 | ok 48/48 |
| dbos | per_turn | duplicate 15/48 | duplicate 15/48 | diverged 15/48 | diverged 15/48 | ok 48/48 |
| restate | per_call | duplicate 12/48 | ok 48/48 | ok 48/48 | ok 48/48 | ok 48/48 |
| restate | per_batch | duplicate 15/48 | ok 48/48 | ok 48/48 | ok 48/48 | ok 48/48 |
| restate | per_turn | duplicate 15/48 | duplicate 15/48 | diverged 15/48 | diverged 15/48 | ok 48/48 |
| langgraph | per_call | duplicate 22/80 | duplicate 1/80 | diverged 1/80 | diverged 1/80 | ok 48/48 |
| langgraph | per_batch | duplicate 41/80 | duplicate 16/80 | diverged 15/80 | duplicate 21/80 | ok 48/48 |
| langgraph | per_turn | duplicate 26/80 | duplicate 25/80 | diverged 27/80 | diverged 25/80 | ok 48/48 |
| langgraph_sync | per_call | duplicate 12/48 | ok 48/48 | diverged 1/48 | diverged 1/48 | ok 48/48 |
| langgraph_sync | per_batch | duplicate 15/48 | ok 48/48 | ok 48/48 | ok 48/48 | ok 48/48 |
| langgraph_sync | per_turn | duplicate 15/48 | duplicate 15/48 | diverged 15/48 | diverged 15/48 | ok 48/48 |

### Where the crash has to land to cause damage (no idempotency key, all models)

| runtime | step granularity | llm_before | llm_after | tool_before | tool_after |
|---|---|---|---|---|---|
| temporal | per_call | ok 24/24 | ok 24/24 | ok 24/24 | duplicate 24/24 |
| temporal | per_batch | ok 24/24 | ok 24/24 | duplicate 6/24 | duplicate 24/24 |
| temporal | per_turn | ok 24/24 | ok 24/24 | duplicate 6/24 | duplicate 24/24 |
| dbos | per_call | ok 24/24 | ok 24/24 | ok 24/24 | duplicate 24/24 |
| dbos | per_batch | ok 24/24 | ok 24/24 | duplicate 6/24 | duplicate 24/24 |
| dbos | per_turn | ok 24/24 | ok 24/24 | duplicate 6/24 | duplicate 24/24 |
| restate | per_call | ok 24/24 | ok 24/24 | ok 24/24 | duplicate 24/24 |
| restate | per_batch | ok 24/24 | ok 24/24 | duplicate 6/24 | duplicate 24/24 |
| restate | per_turn | ok 24/24 | ok 24/24 | duplicate 6/24 | duplicate 24/24 |
| langgraph | per_call | duplicate 3/40 | duplicate 1/40 | duplicate 2/40 | duplicate 40/40 |
| langgraph | per_batch | duplicate 20/40 | duplicate 14/40 | duplicate 10/40 | duplicate 40/40 |
| langgraph | per_turn | duplicate 1/40 | ok 40/40 | duplicate 10/40 | duplicate 40/40 |
| langgraph_sync | per_call | duplicate 1/24 | ok 24/24 | ok 24/24 | duplicate 24/24 |
| langgraph_sync | per_batch | ok 24/24 | ok 24/24 | duplicate 6/24 | duplicate 24/24 |
| langgraph_sync | per_turn | ok 24/24 | ok 24/24 | duplicate 6/24 | duplicate 24/24 |

### Repeated model calls per crashed run (mean extra calls)

| runtime | per_call | per_batch | per_turn |
|---|---|---|---|
| temporal | 0.25 | 0.25 | 0.75 |
| dbos | 0.25 | 0.25 | 0.75 |
| restate | 0.25 | 0.25 | 0.75 |
| langgraph | 0.27 | 0.48 | 0.76 |
| langgraph_sync | 0.27 | 0.25 | 0.75 |
