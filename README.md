# PayOut

A mock cross-border payout service. Transfers move through an explicit state machine and are settled
asynchronously by signed provider webhooks.

- `backend/` — Django + Django REST Framework
- `frontend/` — Next.js (App Router) + TypeScript

## Status

Work in progress. Built in feature branches, one merged PR per slice of behaviour — each PR carries the
code, the tests for the edge cases it introduces, and the reasoning behind the calls made in it.

Sections still to come: how to run, assumptions, architecture, decision log, deliberate omissions,
known limitations.
