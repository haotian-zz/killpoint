# DBOS: a recovered workflow can be picked up by any process with the same application version

This is a note on harness design. It describes how DBOS recovery behaved here, read from debug logs and the 3.6.0 source. I do not consider it a defect in DBOS.

## Versions

dbos 3.6.0, PostgreSQL 17.12.

## What happened

The harness runs many agent runs in parallel. Each run has its own worker process, all sharing one DBOS system database, and each worker is killed and restarted independently.

The first DBOS adapter gave each worker its own `executor_id` and a shared `application_version`. About 1% of crashed runs (5 of 408 in one grid, 16 of 1,224 in another) never finished.

On launch, DBOS finds the pending workflows of its executor id and re-enqueues them on an internal queue. Any process with a matching application version can dequeue from that queue. With debug logging, a worker for run A could be seen dequeuing and executing the recovered workflow of run B. When A's own run finished, its process exited in the middle of B's workflow. B's workflow was then pending under A's executor id, which never launched again, so nothing recovered it and B's worker waited on the result until the deadline.

## Fix in the harness

Each run now uses its own `application_version`. Dequeue filters by version, so a recovered workflow stays with the worker that belongs to it. After the change, 816 DBOS runs and then the full grid finished with no stuck run.

## What it means outside the harness

In a normal deployment every process is a long-lived worker for the same application, so another process picking up a recovered workflow is the intended behavior. The case to watch is a short-lived process, such as a script or a job that starts one workflow and exits when it has its own result, sharing a system database and application version with other work. It can dequeue someone else's recovered workflow and exit partway through it.
