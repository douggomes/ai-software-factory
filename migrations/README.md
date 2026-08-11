# Database migrations

Each `NNNN_description.sql` file is a versioned, forward-only migration
applied in numeric order by `SQLiteRunStore`. This directory — not
`metadata.create_all` — is the effective path that governs how a database is
initialized and upgraded: on open, the adapter reads the persisted
`schema_version`, rejects a version newer than the latest migration here
(fail closed), and applies any pending migrations in order inside a single
transaction.

`0001_initial.sql` is generated from the SQLAlchemy Core metadata in
`src/ai_software_factory/adapters/persistence/schema.py`, which is the
single source of truth for the schema (column types, foreign keys and CHECK
constraints). Do not hand-edit a migration's DDL without regenerating it
from that metadata, or the Python-side table definitions and the executed
SQL will drift apart.

A new migration is a new `NNNN_description.sql` file with the next
sequential version; existing files are never edited or renumbered once
committed, since `schema_version` rows already reference them.
