# Graphify local output

This directory is the local output target for Graphify. Generated reports,
graphs, caches, host-path markers, incremental metadata and token telemetry are
ignored by Git.

Graph files are point-in-time derivatives of source and planning documents.
Versioning them made superseded architectural decisions remain searchable after
the normative documentation changed. Keeping the outputs local avoids treating
a stale generated snapshot as a current contract; Git history retains any
previously published snapshot for audit purposes.

Regenerate the graph from the repository root when it is useful for local
navigation. Do not hand-edit generated JSON, HTML or reports, and do not use a
graph as authority over `AGENTS.md`, ADRs, the active task or the normative
planning documents.
