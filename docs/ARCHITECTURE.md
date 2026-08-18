# VibeStack architecture

Why the system is built the way it is. The code itself stays deliberately light
on commentary; the reasoning lives here.

---

## 1. The shape of the system

```
prompt → parse → blueprint → generate → validate ⇄ heal → review → ledger → package
```

One agent owns one `GenerationState` and calls tools in dependency order. The
only loop is the bounded repair cycle. The only parallel work is the review
council. Everything else is a straight line, on purpose.

---

## 2. Why a single agent, not multi-agent

Backend generation is **dependency-heavy**: the schema constrains the API, which
constrains authentication, which constrains the migrations. Every later decision
depends on an earlier one.

Two well-known positions bracket this question, and they agree about our case:

- **Cognition ("Don't Build Multi-Agents", 2025)** — naive multi-agent systems
  fracture context and compound errors, because sub-agents cannot see each
  other's decisions.
- **Anthropic's multi-agent research system (2025)** — multi-agent beat
  single-agent by ~90%, but only on breadth-first, read-only, *independent*
  search. Their stated limit: domains that require shared context or have many
  dependencies between agents are a poor fit — and they cost roughly 15× the
  tokens.

Our task is exactly the case both describe as unsuitable. Worse, a fragmented
generator would reintroduce the global-consistency problem VibeStack exists to
solve.

**Decision:** one agent, one shared `GenerationState`, specialised work exposed
as *tools* rather than autonomous sub-agents. The "Schema Designer / API
Generator / Auth Engineer" of the original report are `vibestack/tools/*.py`,
called in sequence by `vibestack/agent.py`.

**The one exception — the review council.** Reviewing a *finished* codebase from
five angles is genuinely independent, read-only, breadth-first work where each
reviewer returns a short summary. That is the Anthropic sweet spot, so
`stages/council.py` runs the five lenses in parallel and the orchestrator merges
their findings. They never write code and never coordinate.

---

## 3. Why not LangGraph

The control flow is a deterministic pipeline wrapped in a bounded retry loop.
LangGraph's strength is dynamic, non-prespecified branching over a graph, which
does not apply here, and it adds abstraction layers that hurt readability and
debuggability.

We use an explicit orchestrator with a single typed state object. The one
genuinely useful idea from LangGraph — checkpointing — is kept as about fifteen
lines in `vibestack/checkpoint.py`: serialise the state object after each step.

---

## 4. Where the language model is used, and where it is not

| Task | Approach | Why |
|---|---|---|
| Understanding a prose request | **Model** (`stages/parse.py`) | Ambiguous natural language is what models are genuinely better at. |
| Producing code | **Jinja2 templates** (`renderer.py`, `templates/`) | Deterministic, free, reproducible, unit-testable. The same spec always yields the same files. |
| Diagnosing a build failure | **Ordered rules** (`stages/reflect.py`) | No model call. Free, instant, and testable against real tracebacks. |
| Repairing a build failure | **Model** (`stages/reflect.py`) | Genuine reasoning over an unfamiliar error. |
| Reviewing finished code | **Model** (`stages/council.py`) | Judgement, not mechanism. |

The pattern: **the model handles ambiguity, deterministic code handles
structure.** This is what keeps generation free and repeatable while still
accepting informal input.

`llm_protocol.py` defines a small `StructuredLLM` protocol so stages depend on an
interface rather than on `litellm`. That keeps heavy imports out of the stages
and lets every test pass in a fake client with no network access.

---

## 5. Plan once, then generate

`blueprint.py` plans the entire project before a single file is written: every
spelling of each entity name, which side of a relationship holds the foreign key,
and which entity acts as the account for authentication.

Every tool reads that same plan. This is the mechanism behind global consistency
— the model, the schema, and the router learn a class name from one place rather
than each deciding independently.

Planning also **repairs the specification**, recording each change in the ledger:

- an entity with no primary key is given an `id` column;
- a clear-text `password` field is replaced with `password_hash`;
- an account entity is identified by *shape* (does it carry a login field?) when
  its name is not obviously `User` — this was added after the benchmark caught
  authentication being silently skipped for `Customer`, `Attendee` and `Chef`;
- unsupported many-to-many relationships are reported rather than silently
  dropped.

---

## 6. Validation: proving the code works

Anything can emit plausible-looking code. The difference here is that the project
is actually built and run before the user sees it.

Four gates, cheapest first, in `validation.py` and `resources/gate_runner.py`:

| Gate | Proves |
|---|---|
| `build` | The container image builds — catches a broken Dockerfile or an invented dependency (Docker only) |
| `import` | Every module loads |
| `boot` | The app starts, creates its tables, and answers `/health` |
| `tests` | The generated suite passes |

The gate runner reports a single JSON line on stdout behind a marker, so the
caller never has to infer success from an exit code. It has no dependency on
VibeStack, because it executes inside the generated project's environment.

**Two validators behind one protocol** (`validators/`):

- **Docker** — real isolation for untrusted code: no network during the gates,
  capped CPU, memory and process count, non-root. Also the only way to exercise
  the generated Dockerfile. Honest limit: containers share the host kernel, so
  this is a strong boundary, not a complete one. gVisor or a microVM would be the
  next step.
- **Subprocess** — the same gates on the host. No isolation, but fast, which
  makes it right for tests and CI where the code under test is our own templates.

---

## 7. The self-healing loop

`healing.py`. Two guarantees shape it:

1. **It always terminates.** A circuit breaker caps repair attempts at three, so
   it cannot spend tokens indefinitely on a problem it is not solving.
2. **A failure is always explained.** When the breaker trips, the user gets the
   category, the failing gate, and the log — never silence.

The cycle: validate → classify → repair → re-validate.

**Classification happens before any model call.** `CLASSIFICATION_RULES` in
`stages/reflect.py` is an ordered decision list — the first category whose
markers appear in the log wins. Order matters: `ModuleNotFoundError` is a
subclass of `ImportError`, so the more specific case is checked first. The
resulting category selects targeted repair guidance, so the model is told what
kind of mistake it is looking at instead of inferring it.

**Only the files the traceback names are sent** to the repair model. A traceback
already says where the problem is; sending the whole project on every attempt
would be the obvious approach and also the expensive one.

Two guards protect the project from a bad suggestion: a patch naming a file that
does not exist is rejected, and so is one that would empty a file.

---

## 8. The change ledger

Every generated file carries a recorded reason, every repair says what it fixed,
and every review finding is stored alongside them. This is what makes
AI-generated code auditable rather than merely present.

`ledger_store.py` uses plain `sqlite3` rather than an ORM: three small tables
that never change shape, where an ORM would add a dependency and a layer of
indirection without removing any real work.

---

## 9. Serving it

`api.py` runs generation as a background job because it takes far longer than an
HTTP request should; the client polls for progress. `jobs.py` uses a small thread
pool, since each job spends most of its time waiting on a model or a subprocess.

The application is built by a **factory** (`create_app`) rather than at import
time. Building it opens the ledger database, and importing a module should never
have that kind of side effect.

---

## 10. Things we know are not finished

- The Docker validator has never been exercised against a live daemon.
- Many-to-many relationships are planned around, not supported.
- Job state lives in memory, so a restart loses history even though the ledger
  survives.
- No token or cost accounting exists yet, so the "under five cents per
  generation" figure is currently a design target rather than a measurement.
