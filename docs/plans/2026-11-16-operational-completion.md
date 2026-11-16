# Operational completion implementation plan

> **For agentic workers:** Use superpowers:subagent-driven-development. Execute the already-authorized continuation; do not reopen accepted architecture decisions.

**Goal:** Finish implementable operational gaps and restore the playback incident found during preflight, preserving the media and documenting physical dependencies.

**Architecture:** Keep governance in homelab-control and media in its consumer VMs. One storage authority controls admission. Maintenance must preserve durable idempotency and unresolved operations.

**Tech Stack:** Python 3.12, SQLite, Proxmox/QGA, Compose, Prometheus/Grafana.

**Spec:** `../architecture/gaps.md`, `../architecture/power-recovery.md`, `../runbooks/platform-governance.md`, `../runbooks/storage-core-handoff.md`.

## Global Constraints

- Preserve all media, existing disks, source copies and manual pauses. No formatting, forced/lazy unmount, automatic repair or media deletion.
- Media remains RO in playback; library scans remain suspended; Abyss remains deferred.
- No router openings, RTX, new host units, CI/CD, release or backup manager.
- Existing authorization covers SSH implementation, downtime and publication to refactor. Physical disk identity and mount scope remain explicit.
- Never version secrets, raw inventory, credentials or private evidence. Fixtures must use temporary data.
- Keep one storage authority. Lost QGA output is not proof of process completion or healthy storage.

## Review Focus

- A lost QGA response must not authorize another I/O worker or a stale lease.
- Retention must not remove an idempotency key or any unresolved operation's evidence.
- A successful task response alone must not claim a guest reboot occurred.
- Healthy telemetry targets must not imply Jellyfin or storage admission is healthy.
- Existing source-disk identities from Ubuntu must not authorize blind reattachment or writes after migration.

### Task 1: Restore and diagnose storage admission

- [x] Capture process, lease journal, guest boot, physical disk and fixture evidence.
- [x] Reconcile only the proven completed/orphaned publication under the supervisor lock; preserve its receipt and HOLD before fresh explicit readmission.
- [x] Implement a regression fix only after the cause is demonstrated, with tests for timeout, late/stale result and busy worker refusal.
- [x] Confirm fresh admission, Jellyfin health, catalog preservation and sustained renewal across scheduler handoffs.

### Task 2: Safe governance journal maintenance

Files: `services/control/audit.py`, `services/control/app.py`, `services/control/models.py`, `compose.control.yaml`, `.env.example`, new `tests/test_control_maintenance.py`, `docs/runbooks/platform-governance.md`.

- [x] Add tests that prune events older than 90 days only for terminal operations, preserve every unresolved operation/event and every operation/key, retain valid deletion previews, respect a 500-row batch and remain idempotent.
- [x] Add a maintenance method on the existing store, with the existing transaction/lock. Do not instantiate a second recovery-enabled store for maintenance.
- [x] Run maintenance periodically in the one API process, hourly, with explicit lifecycle cancellation; no host scheduler. Make retention configurable and validate bounds. Do not VACUUM automatically or delete operations.
- [x] Expose sanitized maintenance statistics/limits through an authenticated read endpoint or existing overview, with no actor/parameters/credentials. Test lifecycle and failure behavior: maintenance failure must not bypass journal durability.
- [x] Update runbook and stale Proxmox overview. Test Linux Python 3.12, lint and Compose config; review before deployment.

### Task 3: Operational acceptance and missing signals

- [x] Test shutdown/reboot/start through the private governance API on the empty edge guest with a temporary identity limited to that VM. Prove UPID, state, boot ID, stable SSH identity and restoration. Do not touch core/playback disks or create a guest just for this test.
- [x] Add storage-admission and Jellyfin availability signals to observability with freshness and failure/resolution tests, using restricted existing channels.
- [ ] Deploy reviewed changes, check dashboards/alerts and current resource use, publish sanitized evidence and refactor commits.

### Task 4: Continue the media migration

- [x] Prepare core automation as a separate consumer Compose; retain acquisition/import/destructive work disabled until storage and authorization fixtures pass.
- [ ] Reinventory reconnected source disks, prepare RO source scope and adapt consolidation pins to the new host/guest identities before copying.
- [ ] Prepare the physical recovery procedure with exact mount scope and ordinary teardown/revalidation only. Physical power-loss acceptance requires an assisted test; UPS acquisition remains external.
- [ ] Complete independent work while awaiting disk connection and alert-channel choices. Keep WAN, future HA/K3s and unavailable hardware explicitly pending.

## Execution checkpoint

Core preparation denies startup; it is not activation. Seven core state trees
were restored to new private SSD staging (23.566 GB), with pinned manifest,
selected content hashes/metadata and six SQLite quick checks accepted. Docker
has no application containers. Source disks are connected and inspected under
the specific block-RO/ro,noload scope; pending journals and degraded-source
evidence still require reconciliation before verified consolidation. Alert
delivery is panel-only by user choice. Domains are documented in
`../architecture/access-domains.md`, without DNS/TLS/WAN changes. See the
canonical `../implementation-status.md` for actual measurements and limits.
