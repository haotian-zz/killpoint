# A finished `@task` runs again if the process dies right after it returns

Draft of an upstream report. Not filed, not confirmed by a maintainer.

## Versions

langgraph 1.2.24, langgraph-checkpoint-postgres 3.2.1, PostgreSQL 17.12, Python 3.12.

## What happens

An `@entrypoint` with a `PostgresSaver` calls two tasks in sequence and is invoked with `durability="sync"`:

```python
receipt = charge(effects_file).result()   # appends one line to a file
second = then_die().result()              # SIGKILLs the process first thing
```

`charge` returns and its `.result()` is read before `then_die` starts. After the kill, a new process resumes the thread with `invoke(None, config)`. The file then shows how many times `charge` ran.

| delay between `then_die` starting and the kill | `charge` ran twice |
|---|---|
| 0 ms | 30 of 30 |
| 2 ms | 4 of 30 |
| 10 ms | 0 of 30 |
| 50 ms | 0 of 30 |

With `durability="async"` and no delay it was also 30 of 30.

So the result of a task that has returned is not yet durable when the next task starts, and a crash in the following few milliseconds makes the task run again. The durability setting did not change this.

In the killpoint grid, where an HTTP round trip separates the two points, the same thing showed up in 7 of 120 runs with `sync` and 2 of 120 with `async`.

## Why it matters

The functional API documentation recommends wrapping side effects in tasks so that they are not repeated when a run resumes. That holds once the task's result has reached the checkpointer, but there is a window after the task returns in which it does not hold, and `durability="sync"` reads as if it closed that window.

## Reproduce

```bash
export PG="postgresql://USER:PASSWORD@HOST:PORT/DB"
python langgraph_task_repro.py 30
DELAY_MS=2 python langgraph_task_repro.py 30
DURABILITY=async python langgraph_task_repro.py 30
```

## Question for maintainers

Is a task's result meant to be persisted before `.result()` returns when `durability="sync"`? If the write is intentionally in the background, the durability documentation could say that `sync` applies to checkpoints at step boundaries and not to task results inside an entrypoint.
