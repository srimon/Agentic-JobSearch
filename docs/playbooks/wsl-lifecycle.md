# WSL lifecycle

`jobsearch.service` is enabled for the Ubuntu systemd multi-user target. It starts `startupdocker.sh` after Docker and invokes `stopdocker.sh` during service stop/orderly shutdown before Docker stops. ExecStopPost repeats the idempotent stop to clean up a failed partial startup.

Startup waits up to 120 seconds for configured services to be healthy. Containers receive a 60-second graceful-stop allowance; persistent volumes are retained. This does not change the library service or global Docker configuration.

Use `sudo systemctl start jobsearch`, `sudo systemctl stop jobsearch`, `systemctl status jobsearch`, and `journalctl -u jobsearch` for normal operation. Direct scripts are available for troubleshooting, but direct stop does not change systemd's active marker; manage the systemd unit to keep state consistent.

The unit starts when the Ubuntu WSL distribution boots, not necessarily at Windows sign-in. No Windows Scheduled Task was added. For a deliberate shutdown, run `sudo systemctl stop jobsearch` first if an explicit completed stop is required. Forced termination, host power loss or WSL shutdown deadlines can prevent clean shutdown; database crash recovery and backups are still required.

Testing uses stop/start of this unit only. Shutting down the whole WSL distribution would interrupt the library app and is not part of this verification.

## Verified lifecycle logging

All startup/shutdown entry points now use `scripts/lifecycle.py` through JBS. JSON events go to stdout (systemd journal for service actions) and `logs/lifecycle.jsonl` (5 MiB, three rotated backups). `logs/status.json` records the most recent check result with a timestamp; it is a snapshot, not continuous monitoring. The lifecycle lock prevents concurrent lifecycle operations.

Checks cover Docker availability, configured services, container presence, healthy status, authenticated PostgreSQL/Redis/Qdrant responses, stop completion, OOM and abnormal exit codes. Qdrant SIGTERM exit 143 is accepted; forced kill 137 is not. Failures return nonzero and do not emit lifecycle_verified. Raw Docker output and credentials are not copied into lifecycle records. Container logs retain their own Compose rotation policy.

Use `./scripts/stack.sh status` for a fresh running/healthy check; use `./scripts/stack.sh status stopped` when intentionally stopped. A check for running services while stopped returns failure as expected. `./scripts/stack.sh logs` shows recent lifecycle events. `systemctl status jobsearch` alone is insufficient because the unit is oneshot and does not continually supervise container health.

Library container IDs, start times, running state and restart counts are compared across each operation. Differences are warnings because independent activity or WSL shutdown can also change the library. These checks do not authorize any action on the library. No automatic restart or periodic monitor was added.
