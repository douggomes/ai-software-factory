# ADR 0002 — SQLite as Operational Source of Truth

## Status

Accepted

## Context

The AI Software Factory needs a persistence layer to store run state, task executions, events and other domain aggregates. The system must:

- Survive process restarts without losing state
- Support atomic transactions for state + event writes
- Handle concurrent access from multiple async sessions
- Provide optimistic locking for state transitions
- Remain local and filesystem-based (no external services)

## Decision

SQLite is the authoritative source of truth for all operational state. NDJSON event files are exportable reconstructions, not the primary store.

### Configuration

- **Journal mode**: WAL (Write-Ahead Logging) for concurrent reads during writes
- **Foreign keys**: Enabled to enforce referential integrity
- **Busy timeout**: 5000ms to handle transient contention
- **Session scope**: One `AsyncSession` per concurrent unit (task/attempt)
- **SQL**: Always parameterized to prevent injection

### Implementation

- SQLAlchemy async with aiosqlite driver
- Schema managed via versioned SQL migrations in `migrations/`
- State and events written in the same transaction
- Optimistic version check on task execution transitions

## Consequences

### Positive

- Zero external dependencies — SQLite is embedded
- ACID transactions guarantee state consistency
- WAL mode allows concurrent readers
- Schema migrations are versioned and auditable
- Simple backup via filesystem copy

### Negative

- Single-writer limitation (mitigated by short transactions)
- Not suitable for distributed/multi-node deployments
- Requires careful connection management in async context

### Risks

- Dual write (DB + NDJSON) could diverge — mitigated by making SQLite authoritative
- Concurrent writes may cause `database is locked` — mitigated by busy_timeout and short transactions

## Alternatives Considered

1. **PostgreSQL**: Rejected — requires external service, not local-first
2. **File-based (NDJSON only)**: Rejected — no atomic transactions, no concurrent access
3. **Redis**: Rejected — not persistent by default, requires external service

## References

- [SQLite WAL mode](https://sqlite.org/wal.html)
- [SQLAlchemy asyncio](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- Plan section 10: Persistência e artifacts
