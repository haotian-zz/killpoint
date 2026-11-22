# killpoint

killpoint kills an agent's worker process at a chosen point in its tool-calling loop, lets the durable execution runtime recover, and then checks an external ledger to see how many times each side effect really happened.

It runs the same agent on Temporal, DBOS, Restate and LangGraph (Postgres checkpointer), and reports for each one which crash points leave an external effect duplicated, lost, or recorded differently from what the agent believes.

## The problem

An agent loop asks a model what to do, calls a tool, records the result, and repeats. Many tool calls change something outside the process: a charge, an email, a ticket. A durable execution runtime records each finished step so that a restarted worker can skip it.

The gap is between the moment the external system commits the effect and the moment the runtime records the step as finished. A worker that dies in that gap leaves the runtime with no record of the step, so it runs the step again. This is ordinary at-least-once step execution, which these runtimes are designed around. How much damage the gap does depends on choices the agent developer makes: how much work goes into one step, what the idempotency key is built from, and whether the model repeats itself when asked twice.

## How it works

```
                 +--------------------------------------------+
                 | harness                                    |
                 | start worker, restart it when it dies,     |
                 | grade the run                              |
                 +----+----------------------------------+----+
                      | spawn / respawn                  | read
                      v                                  v
+--------------+   +--------------------+   +----------------------+
| scripted     |<--| the same agent on  |-->| effect ledger        |
| model        |   | temporal / dbos /  |   | records every tool   |
|              |   | restate / langgraph|   | request it receives  |
+--------------+   +---------+----------+   +----------------------+
                             |
                             v
                   +--------------------+
                   | crash oracle       |
                   | "die here": yes,   |
                   | once per run       |
                   +--------------------+
```

The scripted model, the ledger and the crash oracle are one HTTP server inside the harness process (`control.py`). They sit outside every runtime, so the ledger is independent of what a runtime's journal or checkpoint says.

The agent's step bodies are in `agent.py` and are shared by all adapters. An adapter (`runtimes/`) only decides how those bodies are wrapped into the runtime's durable steps. Each step body calls the crash oracle at four points:

| crash point | where the worker dies |
|---|---|
| `llm_before` | before the model is asked |
| `llm_after` | the model has answered, the step has not returned |
| `tool_before` | before the tool request is sent |
| `tool_after` | the external service has applied the effect, the step has not returned |

Death is `SIGKILL` sent by the worker to itself, so no handler or `finally` block runs. The harness then starts the worker again, the way a process supervisor would, and waits for the run to finish.

The workload is four model calls and four tool calls. The model asks for one tool call on turn 1, two on turn 2, one on turn 3, and none on turn 4. That gives 16 crash points, and each cell of the grid gets one run per crash point plus a crash-free baseline.

### What varies

Step granularity, meaning how much work one durable step contains:

- `per_call`: the model call and each tool call are separate steps.
- `per_batch`: the model call is a step, and all tool calls of a turn share one step. This is the shape of a "tools" node that executes every call the model returned.
- `per_turn`: the model call and its tool calls share one step. This is the shape you get by wrapping a whole agent turn, or an agent SDK call, in a single activity.

Idempotency key sent with each tool request:

- `none`
- `args_hash`: a hash of the tool name and arguments.
- `position`: run id, turn and call index.
- `native`: an identifier the runtime gives the step (Temporal activity id, DBOS step id, a Restate `ctx.uuid()` drawn before the step, LangGraph task id), plus the call index.
- `intent_log`: the write-ahead intent log in `intentlog.py`, described under [The intent log](#the-intent-log).

The ledger applies a keyed request only the first time it sees the key and returns the original receipt afterwards.

Model behavior: `deterministic` returns identical arguments when asked the same thing twice. `nondeterministic` returns the same tool calls with a different free-text argument, which is how a real model behaves when it rephrases.

### How a run is graded

- `exactly_once`: every intended tool call took effect once and the agent's history matches the ledger.
- `duplicate`: at least one intended tool call took effect more than once.
- `lost`: at least one intended tool call never took effect, although the run finished.
- `diverged`: effects are exactly-once, but the arguments in the agent's history differ from the arguments the service applied.
- `stuck`: the run did not finish within 90 seconds.

The report also counts repeated model calls, since each one costs money and time on a real model.

Four checks guard the numbers: every crash point was reached, every crashed run restarted exactly once, every crash-free baseline was exactly-once, and no run ended in a harness error.

## Results

8,466 runs, of which 7,968 had a crash. Temporal, DBOS, Restate and LangGraph with `durability="sync"` have three trials per crash point. The LangGraph default configuration has five for the four basic key strategies, because its outcomes depend on timing, and three for the intent log. All four validity checks passed. The full tables are in [RESULTS.md](RESULTS.md) and the raw runs in `results/runs.jsonl`.

Versions: Temporal server 1.32.2 with temporalio 1.36.1, DBOS Transact 3.6.0, Restate server 1.8.1 with restate-sdk 1.5.4, LangGraph 1.2.24 with langgraph-checkpoint-postgres 3.2.1, PostgreSQL 17.12, Python 3.12, on an Apple silicon laptop.

### Temporal, DBOS and Restate behave the same

Across all three, the outcome at every crash point of every cell was identical, and it was the same in each of the three trials.

Without a key, a crash at `tool_after` duplicated the effect in every run (24 of 24 per cell). Crashes at the other three points were harmless when each tool call was its own step. With coarser steps, a crash before the second tool call of a turn also duplicated the first call, because the whole step ran again.

| step granularity | crashed runs with a duplicate, no key |
|---|---|
| `per_call` | 12 of 48 |
| `per_batch` | 15 of 48 |
| `per_turn` | 15 of 48 |

Any of the four key strategies removed the duplicates as long as the model call was a separate step from the tool calls. All three runtimes recovered without help from the application once a worker was back.

### Putting the model call in the same step as its tool calls defeats the key

With `per_turn` steps and a model that rephrases, the retried step asks the model again and gets different arguments.

| key | crashed runs, `per_turn`, nondeterministic model |
|---|---|
| `none` | duplicate 15 of 48 |
| `args_hash` | duplicate 15 of 48 |
| `position` | diverged 15 of 48 |
| `native` | diverged 15 of 48 |
| `intent_log` | exactly-once 48 of 48 |

A key hashed from the arguments changes when the arguments change, so the service sees a new request and applies it. A key taken from the step's position or identity still deduplicates, but the service keeps the effect from the first attempt while the agent's history holds the arguments of the second. The agent then reasons from a record of something that did not happen. The intent log avoids this by reusing the first attempt's arguments.

Coarse steps also repeat model calls. A crashed run repeated 0.25 model calls on average with `per_call` or `per_batch` steps and 0.75 with `per_turn` steps.

### LangGraph with the default durability duplicates effects at more crash points

LangGraph's default `durability="async"` writes each checkpoint in the background while the next step runs. A worker killed during the next step can leave the previous checkpoint unwritten, and the resumed run then repeats work that had finished. Over five trials per crash point, without a key:

| step granularity | crashed runs with a duplicate, deterministic model | nondeterministic model |
|---|---|---|
| `per_call` (functional API) | 24 of 80 | 22 of 80 |
| `per_batch` (model node, tools node) | 43 of 80 | 41 of 80 |
| `per_turn` (one node) | 25 of 80 | 26 of 80 |

With the model node and tools node layout, duplicates followed crashes at every kind of point, including 20 of 40 crashes at `llm_before`, where no tool call was in flight.

Two key strategies that worked elsewhere failed here:

- The task id as key (`native`) left duplicates in 27 of 80 crashed runs with the deterministic model. The retried tools task got a different id from the first attempt, even when the model node did not run again. In a separate check the id changed across recovery in 5 of 6 runs with the default durability and in 0 of 6 with `sync`.
- The argument hash left duplicates in 16 of 80 crashed runs with the nondeterministic model, although the model call was its own node. The model node ran again, and its new arguments produced a new key.

`position` keys removed every duplicate. With the nondeterministic model they left 15 of 80 runs diverged in the model node and tools node layout. With the intent log all 288 crashed runs were exactly-once.

With `durability="sync"` LangGraph matched the other three runtimes, apart from the task result window described below, which showed up in 3 of 384 crashed `per_call` runs.

LangGraph also has no server that restarts an interrupted run. The application has to find the unfinished thread and invoke it again. The adapter does this with `invoke(None, config)`.

### Two LangGraph behaviors that drop or repeat work after a kill

Both have a standalone script in `findings/` that needs only LangGraph and a Postgres database.

1. After a kill, `get_state(config).next` can be an empty tuple for a thread that has not finished. An application that reads an empty `next` as "nothing left to run" abandons the run, and the remaining tool calls never happen. In the script, 17 of 20 killed threads reported an empty `next`, and `invoke(None, config)` completed all 20. See [findings/langgraph-next.md](findings/langgraph-next.md).
2. In the functional API, the saved result of a finished `@task` is lost if the process dies within a few milliseconds of the task returning, so the task runs again on resume. This happens with `durability="sync"` too. In the script the task ran twice in 30 of 30 trials when the kill came immediately, 4 of 30 with a 2 ms delay, and 0 of 30 with a 10 ms delay. See [findings/langgraph-task-durability.md](findings/langgraph-task-durability.md).

Neither has been reported upstream or confirmed by a maintainer.

### The intent log

`intentlog.py` is a small library (one Postgres table, about 100 lines) that came out of these results. Before a tool call is sent, it commits the call's identity (run id, turn, call index) and arguments. A retry of the same call finds that row and sends the same key and the same arguments as the first attempt, whatever the model returned the second time. A call whose result is already recorded is not sent again.

With it, all 1,440 crashed runs were exactly-once, across every runtime, step granularity and model mode, including the `per_turn` and LangGraph default cells where each of the other strategies failed.

It depends on the external service honoring idempotency keys. For a service that does not, `guarded` accepts a `lookup` callback that asks the service whether the earlier attempt took effect before anything is sent again. That path has unit tests and was not exercised in the grid. The log does not reduce repeated model calls.

## What this suggests for agent code

- Give every side-effecting tool call an idempotency key the external service honors. No runtime tested here removes the `tool_after` window by itself.
- Build the key from something fixed before the model is asked, such as the run id and the call's position. A hash of the arguments is only stable while the model call is never repeated.
- Keep the model call in its own durable step, ahead of the tool calls it produces. Otherwise a retry can leave the agent's history disagreeing with the external system even when the key prevents a double effect.
- If the model call cannot be separated from its tool calls, record the intent before sending and reuse the first attempt's arguments on a retry, as `intentlog.py` does.
- On LangGraph, pass `durability="sync"` for runs with side effects, resume with `invoke(None, config)`, and do not use the task id as the key under the default durability.

## Limits

- The only fault is a `SIGKILL` of the worker process. Network partitions, a crash of the runtime's own server, slow or failing external services and timeouts are not tested.
- One kill per run. A second crash during recovery is not tested.
- All four adapters are Python, each written in what I take to be the idiomatic form for that SDK. A different wrapping of the same agent could behave differently.
- The external service is a mock that honors idempotency keys forever. Real services expire keys, and some do not support them at all.
- Three to five trials per crash point. That is enough to see which outcomes are possible and too few to estimate the rate of a rare one, such as the LangGraph task result window.
- Temporal ran with its in-memory development server. The activity start-to-close timeout was set to 5 seconds and the retry interval to 200 ms to keep runs short. Neither changes which steps are retried.
- Workers run one at a time per agent run. Concurrent workers competing for the same run are not tested.

## Running it

Requirements: Docker, Python 3.12, [uv](https://docs.astral.sh/uv/).

```bash
docker compose up -d
docker exec killpoint-postgres-1 psql -U postgres \
  -c "create database killpoint_dbos" -c "create database killpoint_langgraph" \
  -c "create database killpoint_intents"
uv sync

uv run pytest                                  # unit tests; the intent log tests need Postgres
uv run killpoint run --runtimes restate \
  --granularities per_call --keys none         # small grid, well under a minute
uv run killpoint run --parallel 8              # one trial of the full grid, about 45 minutes
uv run killpoint report results/runs.jsonl     # tables
```

`killpoint run` accepts `--runtimes`, `--granularities`, `--llm-modes`, `--keys`, `--crash` (crash kinds, or `none` for baselines only) and `--trials`.

## Adding a runtime

Write `runtimes/<name>_rt.py` with a `run(cfg)` function that starts the agent run or attaches to it if it already exists, waits for it to finish, and calls `agent.report_done`. Wrap `agent.llm_step`, `agent.tool_step`, `agent.batch_step` and `agent.turn_step` in the runtime's durable step primitive. Then add the name to `RUNTIMES` in `spec.py` and to the dispatch in `worker.py`.

A worker must only ever execute its own run. The harness runs many agent runs at once and kills their workers independently, so a worker that picks up another run's work takes that run down when it dies. The adapters get this isolation from a task queue per run (Temporal), an application version per run (DBOS), a service per run (Restate) and a thread per run (LangGraph). [findings/dbos-recovery-queue.md](findings/dbos-recovery-queue.md) describes what went wrong before the DBOS adapter had it.
