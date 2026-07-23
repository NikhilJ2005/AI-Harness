# VibeStack

**An architecture-aware AI software engineering harness** that turns a natural-language
prompt into a runnable, containerized **FastAPI** backend — then *proves it builds*,
*fixes itself* when it doesn't, and *records the rationale* behind every file.

> **Status:** Planning complete — implementation starting (Phase 0).
> See [`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md) for the full architecture and roadmap.

## The problem

Mainstream AI app builders (Lovable, Bolt.new, v0) are locked to JavaScript/TypeScript,
cloud-hosted, and export nothing you can own. Meanwhile AI-generated code is routinely
merged without anyone understanding *why* it looks the way it does — causing architectural
drift and hidden technical debt.

## What VibeStack does

Type *"a blog API with users, posts, comments and JWT auth"* and get back a complete
FastAPI project that:

- **Provably builds and boots** — validated inside a Docker sandbox (import → boot → tests).
- **Self-heals** — if a build gate fails, it classifies the error, patches it, and retries,
  bounded to 3 attempts by a circuit breaker so it never loops forever.
- **Explains itself** — every change is recorded in a SQLite **change ledger** with its
  rationale and impact.
- **Is yours** — delivered as a standard Docker + `pyproject.toml` workspace. Self-hosted,
  no vendor lock-in.

## Architecture at a glance

A single agent owns one shared context and calls tools in a deterministic pipeline:

```
NL prompt → Parse (→ typed ProjectSpec) → Generate (schema/API/auth/migrations/devops)
          → Validate in Docker → [Self-heal loop] → Review council → Ledger → Package
```

Two deliberate design decisions (both detailed in the plan):

- **No LangGraph.** The flow is a deterministic pipeline plus a bounded retry loop, so an
  explicit Python orchestrator is simpler and fully explainable.
- **Single agent with tools, not multi-agent.** Backend generation has tightly dependent
  outputs (schema → API → auth), which is the wrong fit for multi-agent systems that
  fragment context. Read-only parallelism is reserved for the review council.

## Tech stack

Python 3.11 · FastAPI · Pydantic v2 · instructor · LiteLLM (OpenRouter) · Jinja2 ·
SQLAlchemy · Alembic · Docker · pytest · UV

## Roadmap

| Phase | Goal |
|---|---|
| P0 | Skeleton — spec parsing + CLI |
| P1 | Happy-path generation (CRUD + auth) |
| P2 | Docker validation + self-healing loop |
| P3 | Change ledger + review council + API |
| P4 | Polish, benchmark, demo |

See [`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md) for the full detail, component choices,
and team task board.

## Project

Final-year project — B.Tech CSE (Artificial Intelligence), Muthoot Institute of Technology
and Science (Autonomous), Kochi.

**Team:** Reuben Sabu V · Sidharth Ravi · Jino Jenz · Nikhil Jimmy &nbsp;·&nbsp; **Guide:** Nimmi M K
