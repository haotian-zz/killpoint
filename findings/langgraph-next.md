# `get_state().next` is empty for a killed, unfinished thread

Draft of an upstream report. Not filed, not confirmed by a maintainer.

## Versions

langgraph 1.2.24, langgraph-checkpoint-postgres 3.2.1, PostgreSQL 17.12, Python 3.12.

## What happens

A graph `a -> b` runs with a `PostgresSaver` and the default durability. The process is killed with `SIGKILL` inside node `b`, about 2 ms after `b` starts. Node `b` never completes, so the thread is unfinished.

A new process then calls `graph.get_state(config)`. In 17 of 20 trials `snapshot.next` was `()`. In the other 3 it was `('__start__',)`. With a 5 ms delay before the kill the split was `('b',)` 11, `()` 8, `('__start__',)` 1.

In the same state, the newest entry of `get_state_history(config)` reports a non-empty `next`, and `graph.invoke(None, config)` resumes and completes the run. This held in all 20 trials.

Inspecting one such thread from the killpoint harness showed the latest stored checkpoint was the one taken before the finished node, with that node's writes saved as pending writes. `get_state` returned values with those writes applied and no next task.

## Why it matters

`snapshot.next` is the documented way to see which nodes run next, and an empty tuple is commonly read as "this thread is done". An application that decides whether to resume by checking `if snapshot.next:` drops these threads. In the killpoint harness an earlier version of the LangGraph adapter did exactly that, and runs finished with tool calls that were never executed.

## Reproduce

```bash
export PG="postgresql://USER:PASSWORD@HOST:PORT/DB"
python langgraph_next_repro.py
DELAY_MS=5 python langgraph_next_repro.py
```

## Question for maintainers

Is `next == ()` the intended result of `get_state` when the latest checkpoint has pending writes for all of its tasks and the following checkpoint was never written? If so, the documentation for resuming after a failure could say that `invoke(None, config)` should be called without consulting `next`.
