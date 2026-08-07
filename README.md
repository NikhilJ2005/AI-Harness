# VibeStack

**An architecture-aware AI software engineering harness** that turns a natural-language
prompt into a runnable, containerized **FastAPI** backend — then *proves it builds*,
*fixes itself* when it doesn't, and *records the rationale* behind every file.

> **Status:** Phase 1 complete — VibeStack generates a complete, working FastAPI backend
> (SQLAlchemy models, Pydantic schemas, CRUD routers, JWT auth, Docker, and tests) from a
> specification. The generated project boots and passes its own test suite.
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

## Getting started

```bash
# 1. Install (editable, with dev dependencies for the test suite)
pip install -e ".[dev]"

# 2. Configure your model access
cp .env.example .env        # then add your OpenRouter API key to .env

# 3. Generate a backend from a natural-language prompt
python -m vibestack "a blog API with users, posts and JWT auth" --out ./generated-backend

# 4. Run the tests (no API key or network required)
python -m pytest
```

**No API key?** Generation itself is deterministic and needs no model access — you can
generate straight from a specification file:

```bash
python -m vibestack --from-spec examples/blog_api.json --out ./generated-backend
cd generated-backend && docker compose up --build
```

Add `--spec-only` to print the `ProjectSpec` as JSON without generating files.

### Where the language model is used

The model is used for the one job it is genuinely better at — reading informal prose and
turning it into a structured `ProjectSpec`. Code generation itself is deterministic and
template-driven, so the same spec always produces the same files, generation costs nothing,
and every output is unit-testable. The model returns in Phase 2 to *diagnose and repair*
build failures.

## Roadmap

| Phase | Goal | Status |
|---|---|---|
| P0 | Skeleton — spec parsing + CLI | ✅ Done |
| P1 | Happy-path generation (CRUD + auth) | ✅ Done |
| P2 | Docker validation + self-healing loop | Next |
| P3 | Change ledger + review council + API | Planned |
| P4 | Polish, benchmark, demo | Planned |

See [`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md) for the full detail, component choices,
and team task board.

## Project

Final-year project — B.Tech CSE (Artificial Intelligence), Muthoot Institute of Technology
and Science (Autonomous), Kochi.

**Team:** Reuben Sabu V · Sidharth Ravi · Jino Jenz · Nikhil Jimmy &nbsp;·&nbsp; **Guide:** Nimmi M K
