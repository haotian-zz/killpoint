Runs: 3672 (3456 with a crash, 216 baselines).

Validity checks: all passed.

### Outcome of crashed runs, deterministic model

| runtime | step granularity | key: none | key: args_hash | key: position | key: native |
|---|---|---|---|---|---|
| temporal | per_call | duplicate 4/16 | ok 16/16 | ok 16/16 | ok 16/16 |
| temporal | per_batch | duplicate 5/16 | ok 16/16 | ok 16/16 | ok 16/16 |
| temporal | per_turn | duplicate 5/16 | ok 16/16 | ok 16/16 | ok 16/16 |
| dbos | per_call | duplicate 4/16 | ok 16/16 | ok 16/16 | ok 16/16 |
| dbos | per_batch | duplicate 5/16 | ok 16/16 | ok 16/16 | ok 16/16 |
| dbos | per_turn | duplicate 5/16 | ok 16/16 | ok 16/16 | ok 16/16 |
| restate | per_call | duplicate 4/16 | ok 16/16 | ok 16/16 | ok 16/16 |
| restate | per_batch | duplicate 5/16 | ok 16/16 | ok 16/16 | ok 16/16 |
| restate | per_turn | duplicate 5/16 | ok 16/16 | ok 16/16 | ok 16/16 |
| langgraph | per_call | duplicate 24/80 | ok 80/80 | ok 80/80 | ok 80/80 |
| langgraph | per_batch | duplicate 43/80 | ok 80/80 | ok 80/80 | duplicate 27/80 |
| langgraph | per_turn | duplicate 25/80 | ok 80/80 | ok 80/80 | ok 80/80 |
| langgraph_sync | per_call | duplicate 5/16 | ok 16/16 | ok 16/16 | ok 16/16 |
| langgraph_sync | per_batch | duplicate 5/16 | ok 16/16 | ok 16/16 | ok 16/16 |
| langgraph_sync | per_turn | duplicate 5/16 | ok 16/16 | ok 16/16 | ok 16/16 |

### Outcome of crashed runs, nondeterministic model

| runtime | step granularity | key: none | key: args_hash | key: position | key: native |
|---|---|---|---|---|---|
| temporal | per_call | duplicate 4/16 | ok 16/16 | ok 16/16 | ok 16/16 |
| temporal | per_batch | duplicate 5/16 | ok 16/16 | ok 16/16 | ok 16/16 |
| temporal | per_turn | duplicate 5/16 | duplicate 5/16 | diverged 5/16 | diverged 5/16 |
| dbos | per_call | duplicate 4/16 | ok 16/16 | ok 16/16 | ok 16/16 |
| dbos | per_batch | duplicate 5/16 | ok 16/16 | ok 16/16 | ok 16/16 |
| dbos | per_turn | duplicate 5/16 | duplicate 5/16 | diverged 5/16 | diverged 5/16 |
| restate | per_call | duplicate 4/16 | ok 16/16 | ok 16/16 | ok 16/16 |
| restate | per_batch | duplicate 5/16 | ok 16/16 | ok 16/16 | ok 16/16 |
| restate | per_turn | duplicate 5/16 | duplicate 5/16 | diverged 5/16 | diverged 5/16 |
| langgraph | per_call | duplicate 22/80 | duplicate 1/80 | diverged 1/80 | diverged 1/80 |
| langgraph | per_batch | duplicate 41/80 | duplicate 16/80 | diverged 15/80 | duplicate 21/80 |
| langgraph | per_turn | duplicate 26/80 | duplicate 25/80 | diverged 27/80 | diverged 25/80 |
| langgraph_sync | per_call | duplicate 4/16 | ok 16/16 | ok 16/16 | ok 16/16 |
| langgraph_sync | per_batch | duplicate 5/16 | ok 16/16 | ok 16/16 | ok 16/16 |
| langgraph_sync | per_turn | duplicate 5/16 | duplicate 5/16 | diverged 5/16 | diverged 5/16 |

### Where the crash has to land to cause damage (no idempotency key, all models)

| runtime | step granularity | llm_before | llm_after | tool_before | tool_after |
|---|---|---|---|---|---|
| temporal | per_call | ok 8/8 | ok 8/8 | ok 8/8 | duplicate 8/8 |
| temporal | per_batch | ok 8/8 | ok 8/8 | duplicate 2/8 | duplicate 8/8 |
| temporal | per_turn | ok 8/8 | ok 8/8 | duplicate 2/8 | duplicate 8/8 |
| dbos | per_call | ok 8/8 | ok 8/8 | ok 8/8 | duplicate 8/8 |
| dbos | per_batch | ok 8/8 | ok 8/8 | duplicate 2/8 | duplicate 8/8 |
| dbos | per_turn | ok 8/8 | ok 8/8 | duplicate 2/8 | duplicate 8/8 |
| restate | per_call | ok 8/8 | ok 8/8 | ok 8/8 | duplicate 8/8 |
| restate | per_batch | ok 8/8 | ok 8/8 | duplicate 2/8 | duplicate 8/8 |
| restate | per_turn | ok 8/8 | ok 8/8 | duplicate 2/8 | duplicate 8/8 |
| langgraph | per_call | duplicate 3/40 | duplicate 1/40 | duplicate 2/40 | duplicate 40/40 |
| langgraph | per_batch | duplicate 20/40 | duplicate 14/40 | duplicate 10/40 | duplicate 40/40 |
| langgraph | per_turn | duplicate 1/40 | ok 40/40 | duplicate 10/40 | duplicate 40/40 |
| langgraph_sync | per_call | duplicate 1/8 | ok 8/8 | ok 8/8 | duplicate 8/8 |
| langgraph_sync | per_batch | ok 8/8 | ok 8/8 | duplicate 2/8 | duplicate 8/8 |
| langgraph_sync | per_turn | ok 8/8 | ok 8/8 | duplicate 2/8 | duplicate 8/8 |

### Repeated model calls per crashed run (mean extra calls)

| runtime | per_call | per_batch | per_turn |
|---|---|---|---|
| temporal | 0.25 | 0.25 | 0.75 |
| dbos | 0.25 | 0.25 | 0.75 |
| restate | 0.25 | 0.25 | 0.75 |
| langgraph | 0.27 | 0.50 | 0.76 |
| langgraph_sync | 0.27 | 0.25 | 0.75 |
