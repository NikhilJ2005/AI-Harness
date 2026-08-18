# Demo walkthrough

A ten-minute run through VibeStack that shows the whole system working. Every
step below runs **without an API key**, so nothing depends on the network.

Set up once, before the audience is watching:

```bash
pip install -e ".[dev]"
```

---

## 1. The claim (30 seconds)

> AI coding tools generate fast, but they hand you code nobody understands and
> that often does not even run. VibeStack turns a plain-English request into a
> FastAPI backend that **provably builds**, **fixes itself** when it does not,
> and **explains every decision** — all self-hosted, so you own the code.

## 2. Generate a backend (1 minute)

```bash
python -m vibestack --from-spec examples/blog_api.json --out demo-backend --sandbox subprocess
```

Point at three things in the output:

- **25 files** — models, schemas, routers, auth, Dockerfile, compose, tests.
- **The ledger** — every file has a reason next to it, in plain English.
- **`Validation: passed`** — this is the difference. The project was built and
  run before it was handed over.

## 3. Prove it actually works (1 minute)

```bash
cd demo-backend
python -m pytest            # the generated tests
uvicorn app.main:app --port 8000
```

Open <http://localhost:8000/docs>. Register a user, log in, call `/auth/me` with
the token. The interactive docs make this fast and visual.

Worth saying out loud: **the password hash is stored but never appears in any
response** — the schemas exclude it, and there is a test asserting that.

## 4. Show the self-healing loop (2 minutes)

This is the headline. Break the project on purpose:

```bash
cd demo-backend
# Delete an import that is still used
sed -i 's/, Text//' app/models/post.py
```

Then validate it:

```bash
cd ..
python -c "
from pathlib import Path
from vibestack.checkpoint import load_checkpoint
from vibestack.healing import validate_and_heal
from vibestack.validators import SubprocessValidator

project = Path('demo-backend')
state = load_checkpoint(project)
validate_and_heal(state, project, SubprocessValidator(), llm=None,
                  on_progress=lambda message: print(' ', message))
print(state.error_log[:400])
"
```

It reports:

```
Validation failed at the 'import' gate. Diagnosis: undefined_name.
```

Two points to make here:

- The **diagnosis is deterministic** — no model was called to work out what kind
  of error this is. That is an ordered rule set, so it is free, instant, and
  unit tested against real tracebacks.
- With an API key configured, the loop would now send **only the file the
  traceback names** to the model, apply the patch, and re-validate — bounded to
  three attempts by a circuit breaker so it can never loop forever.

## 5. The web UI (2 minutes)

```bash
uvicorn vibestack.api:create_app --factory --reload
```

Open <http://localhost:8000> and press **"Use example spec (no API key)"**.

Show the live progress list, then the **change ledger** below it. Scroll to the
first entry:

```
[plan] (specification)   Added 'password_hash' to User to store passwords.
```

That is the architecture-aware part: the tool noticed the specification had
nowhere to store a password, fixed it, and **told you why**. Finish by pressing
**Download project**.

## 6. The benchmark (1 minute)

```bash
python -m vibestack.benchmark
```

Ten diverse specifications, **10/10 passing**, about 2.5 seconds each. Mention
that the benchmark found a real bug during development: authentication was being
silently skipped whenever the account entity was not literally called `User`.
Detection now matches on shape — does the entity have a login field — and the
regression test for it is in the suite.

## 7. Close with the engineering judgment (1 minute)

Two decisions to be ready to defend, because interviewers ask:

**Why not LangGraph?**
> The control flow is a deterministic pipeline wrapped in a bounded retry loop.
> LangGraph's strength is dynamic branching over a graph, which does not apply
> here, and it adds abstraction that hurts readability. We used an explicit
> orchestrator with one typed state object, and kept the one idea worth keeping
> — checkpointing — as about fifteen lines.

**Single agent or multi-agent?**
> Single agent with tools. Backend generation is dependency-heavy: the schema
> drives the API drives auth. Both Cognition and Anthropic report that
> dependency-heavy, shared-context work is where multi-agent systems fail,
> because sub-agents cannot see each other's decisions. We use parallelism in
> exactly one place — the review council — where the five perspectives are
> genuinely independent and read-only.

---

## Numbers to have ready

| Metric | Value |
|---|---|
| Benchmark specifications passing every gate | 10/10 (100%) |
| Average generation and validation time | ~2.5s |
| Average files per generated project | ~23 |
| Test suite | 113 tests |
| Repair attempt ceiling | 3 (circuit breaker) |

## If the demo breaks

- **No FastAPI installed** — `pip install -e ".[dev]"` then `pip install fastapi uvicorn sqlalchemy pyjwt bcrypt python-multipart httpx`.
- **Port already in use** — add `--port 8010`.
- **Docker not running** — pass `--sandbox subprocess`; everything above works without Docker.
- **Nothing works** — fall back to the recorded video and the benchmark output,
  both of which stand on their own.
