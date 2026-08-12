# Graphify architecture snapshot

This directory contains a reviewable architecture snapshot generated from the
repository at commit `ed67e5d67f3b654359f5f14c436a68652fe0f3a2`.

## Versioned artifacts

- [`GRAPH_REPORT.md`](GRAPH_REPORT.md): human-readable architecture report.
- [`graph.json`](graph.json): machine-readable graph with nodes, edges, and
  inferred relationships.
- [`graph.html`](graph.html): interactive visualization with the graph data
  embedded in the page.

The HTML viewer loads `vis-network` 9.1.6 from unpkg with Subresource Integrity
(SRI), so opening it requires network access for that pinned dependency. The
Markdown report and JSON graph remain usable offline.

## Local-only artifacts

Graphify also generates caches, absolute host-path markers, incremental file
metadata, and token-cost telemetry. Those files are intentionally ignored by
Git because they are machine-specific, reproducible, or operational rather
than part of the architecture snapshot.

When refreshing the graph, run Graphify from the repository root and commit
the three versioned artifacts together so the report, data, and viewer remain
consistent.
