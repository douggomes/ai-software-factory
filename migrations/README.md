# Database migrations

Each `NNNN_description.sql` file is a versioned, forward-only migration
applied in numeric order by `SQLiteRunStore`. This directory — not
`metadata.create_all` — is the effective path that governs how a database is
initialized and upgraded: on open, the adapter reads the persisted
`schema_version`, rejects a version newer than the latest migration here
(fail closed), and applies any pending migrations in order inside a single
transaction.

Every migration records its own version in `schema_version` as its final
statement. The runner verifies that the recorded version matches the filename
before proceeding. This keeps the schema change and its version marker in the
same transaction.

`src/ai_software_factory/adapters/persistence/schema.py` describes the latest
schema for typed queries. Forward migrations must bring an older database to
that same shape. A schema change never rewrites an existing migration: for
example, `0002_harden_constraints.sql` rebuilds V1 tables to add constraints
that SQLite cannot add in place.

A new migration is a new `NNNN_description.sql` file with the next
sequential version; existing files are never edited or renumbered once
committed, since `schema_version` rows already reference them.

The wheel build includes this directory at
`ai_software_factory/migrations`. Runtime discovery uses package resources in
an installed artifact and falls back to this root directory only in a source
checkout. The packaging smoke test must build the wheel, import from that wheel
and initialize a fresh store.
