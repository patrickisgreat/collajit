# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`collajit` makes digital art from large image collections — hundreds to thousands
of images. Three art modes: **photo mosaic**, **generative/algorithmic layouts**,
and **freeform layered collage**.

**The UI is a Tauri desktop app** (Rust shell → React/Vite frontend → local FastAPI
backend that wraps the Python core). The Python compute core is UI-agnostic and is
the source of truth; the Qt/PySide6 app (`collajit.ui`, `python -m collajit`) is the
**legacy** first UI, kept working but superseded by the web/Tauri UI.

### Run

```bash
# Desktop app (built .app):
open frontend/src-tauri/target/release/bundle/macos/collajit.app
# Desktop app, dev (hot reload; spawns backend via .venv):
cd frontend && npm run tauri dev
# Build the .app:
cd frontend && npm run tauri build
# Web app only (one process serves API + built UI): open http://127.0.0.1:8756
.venv/bin/collajit-server
# Legacy Qt UI:
.venv/bin/python -m collajit
```

The Tauri shell (`frontend/src-tauri/src/lib.rs`) spawns `.venv/bin/collajit-server`
on launch (found by walking up from the executable to the repo root, so `.env`
loads) and kills it on exit. Distribution to machines without the `.venv` needs a
PyInstaller sidecar (not yet built — `spawn_backend()` already prefers a `collajit-server`
binary next to the executable if present).

## Environment

The interpreter is a venv on Homebrew **Python 3.14** at `./.venv` (the system
`/usr/bin/python3` is 3.9 and the Homebrew `python@3.12` bottle is broken on this
machine — an `expat` symbol mismatch). Always use `.venv/bin/python`.

```bash
.venv/bin/python -m pip install -e ".[dev]"   # set up / refresh deps
```

## Commands

```bash
# Run the editor
.venv/bin/python -m collajit          # or: .venv/bin/collajit

# Tests (offscreen so the UI smoke tests run without a display)
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest

# A single test
.venv/bin/python -m pytest tests/test_generators.py::test_mosaic_size_and_color_match

# Coverage (CI enforces a 75% floor)
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest --cov=collajit --cov-fail-under=75

# Lint / autofix
.venv/bin/ruff check src tests
.venv/bin/ruff check --fix src tests

# Frontend (React/Vite) — unit tests + type-check + build
cd frontend && npm test && npm run build
```

CI (`.github/workflows/ci.yml`) runs all of the above on every push to `main` and
every PR: Python lint+test+coverage (ubuntu), frontend test+build (ubuntu), and a
full Tauri `.app` build (macOS). `release.yml` builds + publishes the `.app` on a
`v*` tag.

## Architecture

The codebase is a strict stack — lower layers never import higher ones. The
central design idea: **every art mode produces `Layer`s, and a single compositor
renders the layer stack to the final image.** Generate, preview, and export all
go through that one path, so what you see is what you export.

```
engine/  ── pure image logic, ZERO Qt imports (headless, fully unit-tested)
  image_ops   load/resize/crop/tint, PIL<->float-RGBA-array conversions
  features    per-image feature vector (mean RGB + 4x4 grid + HSV hist); FEATURE_VERSION
  matcher     NearestNeighbors index + greedy diversity-aware assignment (mosaic)
  compositor  blend a list of PlacedLayers -> (H,W,4) float image (W3C blend modes)
              `rasterize()` turns a Layer's source+transform into a PlacedLayer

model/   ── the document
  layer       Layer = source (disk path OR in-memory image) + Transform + opacity/blend
  project     Project = canvas size + ordered (bottom-first) layer list; render/save/load/export

library/ ── the source-image catalog (cached in ~/.collajit, override with $COLLAJIT_HOME)
  catalog     SQLite: one row/image with mtime, dims, thumbnail path, feature blob
  ingest      incremental folder scan -> thumbnails + features (skips unchanged files)

generators/ ── the three art modes (consume the library, emit composition output)
  mosaic      rebuild a target from best-matching tiles; returns one composite PIL image
  generative  colour-sort grid OR PCA/t-SNE embedding snapped to a grid; one composite image
  freeform    scatter library images as MANY editable Layers (kept high-res & movable)

fetch/   ── pull source images from the web into the library (all keyless/CC sources)
  sources/    Openverse / Wikimedia / Met adapters behind one ImageSource interface;
              they take an injectable HttpClient (RequestsHttp default) so tests run offline
  planner     derive palette-spanning queries from the target's colours, budget count across them
  downloader  concurrent download, decode-verify + min-resolution filter, hash-dedupe, manifest.jsonl
  tagger      OPTIONAL Claude-vision term suggestion (anthropic SDK, claude-opus-4-8); only fills
              the terms box — typed terms always work and take precedence
  service     run_fetch(): plan → search all sources → download → ingest into the catalog

server/  ── FastAPI backend (the API the web/Tauri UI calls; reuses the core)
  app         create_app(): REST + SSE over library/fetch/generators/project; serves
              frontend/dist at / when built; physical-sizing + no-repeat live here
  jobs        in-process JobManager: long ops run on threads, progress streamed via SSE

ui/      ── PySide6 editor (LEGACY Qt UI; superseded by the Tauri app)
  main_window owns the Catalog + active Project; turns panel signals into model edits
  canvas      QGraphicsView; each Layer is a movable LayerItem, edits write back to the model
  worker      run_async(): heavy work on QThreadPool, off the UI thread
```

Outside the Python package:

```
frontend/         Vite + React + TS UI (the real front end)
  src/api.ts      thin client: REST helpers + runJob() SSE subscriber; API_BASE = :8756
  src/App.tsx     layout + Library / Fetch / Mosaic / Generative tabs + Preview
  src-tauri/      Tauri 2 (Rust) desktop shell; lib.rs spawns/kills the backend
```

### Things worth knowing before you change code

- **Keep `engine/` and `generators/` Qt-free.** They're the testable core and are
  imported headless in CI. `app.main()` imports Qt lazily for the same reason.
- **Mosaic/generative return a baked `PIL.Image`; freeform returns `Layer`s.** The
  first two become a single in-memory composite layer; freeform stays editable.
- **In-memory vs path-backed layers:** generator composites live in `Layer._image`
  until `Project.save()` writes them into `<name>_assets/` and sets `Layer.path`.
- **Feature space is shared.** Mosaic features each *target cell* with the *same*
  `extract_features` used on source images, so matching is apples-to-apples. If you
  change the feature layout, bump `FEATURE_VERSION` (catalog auto-invalidates).
- **Transform convention:** `Transform.cx/cy` is the layer's *centre* in canvas px;
  the canvas sets the item's transform origin to its centre so scale/rotation pivot
  there. Keep `canvas` and `compositor.rasterize` consistent if you touch this.
- The catalog/thumbnails persist under `~/.collajit`. Tests isolate it via the
  `COLLAJIT_HOME` env var (see `tests/conftest.py`). Fetched images land in
  `~/.collajit/fetched/<slug>/` and are auto-ingested.
- **Fetch is Qt-free and network-isolated for tests.** Sources never import
  `requests` directly — they take an `HttpClient`; `tests/test_fetch.py` injects a
  `FakeHttp`. Don't add real network calls to the test suite.
- **Claude vision tagging** needs `ANTHROPIC_API_KEY` (or `ANTHROPIC_AUTH_TOKEN`).
  `app.main()` calls `config.load_env()` first, which loads a project-root `.env`
  (via python-dotenv, real env vars win) — so the key lives in `.env` (gitignored;
  `.env.example` is the template), not the shell. `tagger.suggest_terms` raises a
  friendly `RuntimeError` if it's missing, and the UI falls back to typed terms. It
  uses `claude-opus-4-8` with a JSON-schema output — see the `claude-api` skill
  before changing it.


### Clean Code

- **DRY**: Do not repeat yourself. Extract shared logic into reusable functions/modules. If you see duplication, refactor it.
- **SRP (Single Responsibility Principle)**: Every function, module, and component should do one thing. If a function needs an "and" to describe it, split it.
- **Small, modular functions**: Keep functions short and focused. Prefer many small composable functions over few large ones. Each should be independently understandable and testable.
- **Never over-engineer**: Write the minimum code needed to solve the problem correctly. No speculative abstractions, premature generalization, or "just in case" code. Simple and clear beats clever.
- **Naming**: Use descriptive, intention-revealing names. Code should read like prose — minimize the need for comments by making the code self-documenting.
- **No dead code**: Remove unused imports, variables, functions, and commented-out code. Don't leave TODOs without action.

## Testing

No PR is mergeable without tests that cover the behavior introduced or changed in that PR.

This is not negotiable. If the code is worth shipping, it is worth testing. If it is too hard to test, that is a signal the code needs to be restructured, not that the test can be skipped.

---

### The Testing Pyramid

Follow the testing pyramid. Violations of the pyramid's proportions are a code smell.

```
        /\
       /  \
      / E2E\
     /------\
    /  Integ- \
   / ration    \
  /-------------\
 /   Unit Tests  \
/-----------------\
```

**Unit tests** form the base. They should be the majority of your test suite. Fast, isolated, no I/O, no network, no database. They test a single function or class in complete isolation. If your unit tests are slow, they are not unit tests.

**Integration tests** sit in the middle. They test that components work correctly together — a service and its database, a handler and its dependencies, a module and the interface it consumes. You need fewer of these than unit tests, and they are allowed to be slower.

**End-to-end tests** sit at the top. They are few, they are slow, and they test only the critical paths a real user would take through the system. You do not need an E2E test for every feature. You need one for every path that would be catastrophic to break silently.

The pyramid gets inverted in a lot of codebases — a handful of unit tests and a mountain of E2E tests. This is a trap. E2E tests are brittle, slow, and expensive to maintain. They should be the last line of defense, not the first.

---

### Unit Tests

- Every new function or method gets unit tests.
- Test behavior, not implementation. If your test breaks when you rename an internal variable, it is testing the wrong thing.
- Tests should be fast enough that running the full unit suite feels instant. If a test requires real I/O, it is an integration test — move it.
- Use mocks and stubs at integration boundaries (network, filesystem, database, time). Do not mock your own code — if you find yourself mocking internal collaborators, the design needs work.
- A test that cannot fail is not a test. After writing a test, verify it can fail by temporarily breaking the implementation.
- Tests are documentation. A well-written test tells the reader what the system is supposed to do. Name tests accordingly: `it("returns an error when the user is not found")` not `it("works correctly")`.

---

### Integration Tests

- New service boundaries, API endpoints, database interactions, and message queue consumers all need integration tests.
- Integration tests should use real infrastructure where practical. Prefer a real test database over a mocked one. Docker Compose or your CI environment should provision dependencies.
- Test the contract at the boundary, not the internals. An integration test for an API endpoint should test the request/response shape, status codes, and side effects — not the internal call graph.
- Keep integration tests isolated from each other. Tests that depend on execution order or shared mutable state are land mines. Seed and tear down data per test or per suite.

### Coverage

- Coverage is a floor, not a goal. 100% coverage with meaningless tests is worthless. 80% coverage with tests that actually verify behavior is valuable.
- Coverage reports are useful for finding untested paths, not for hitting a number. Use them that way.
- New code should not lower coverage. CI should enforce this.

---

### What is not an acceptable excuse

- **"It's just a small change."** Small changes break things. Small tests are also small.
- **"It's hard to test."** Make it testable. Difficulty testing is almost always a design signal.
- **"I'll add tests in a follow-up PR."** You won't. No one ever does. Tests go in the same PR or the PR does not merge.
- **"The existing tests cover it."** Show that they do. Say so explicitly in the PR description. If they don't, add tests.
- **"It's just a UI change, it doesn't need tests."** New UI gets Playwright tests. See above.

### Security

- **Security is a priority, not an afterthought.**
- Never commit secrets, tokens, or credentials. Use `.env.local` and ensure `.gitignore` covers sensitive files.
- Validate and sanitize all user input at system boundaries (file uploads, form data, URL params).
- Use parameterized queries — never construct SQL strings manually.
- Follow OWASP top 10 guidance: guard against XSS, injection, CSRF, and insecure deserialization.
- Supabase RLS (Row Level Security) policies must be in place for all database tables.
- Treat WASM input from JS as untrusted — validate array lengths, image dimensions, and parameter ranges in Rust before processing.
- Review dependencies for known vulnerabilities (`pnpm audit`).

### Git Workflow

- **Always work from a feature branch.** Never commit directly to `main`. Create a descriptive branch name like `feat/improve-penalty-calc` or `fix/wasm-loader-fallback`.
- **Commit often.** Make small, frequent commits that each represent a logical unit of work. Don't batch unrelated changes into one commit.
- **Conventional commit messages.** Use prefixes:
  - `feat:` — New feature or capability
  - `fix:` — Bug fix
  - `refactor:` — Code restructuring with no behavior change
  - `test:` — Adding or updating tests
  - `chore:` — Build, CI, dependency updates, tooling
  - `docs:` — Documentation changes
  - `perf:` — Performance improvements
  - `style:` — Formatting, whitespace (no logic changes)
- **Messages should be concise and meaningful.** Describe _what_ and _why_, not _how_. Example: `feat: add beam search lookahead to pin selection` not `update string_art.rs`.
- **Submit PRs back to `main` using `gh pr create`.** PRs need clear titles using the same conventional prefixes. Include a summary of changes and a test plan in the PR body.
- **The user will review all PRs before merge.** Do not merge PRs autonomously.
- **NEVER add `Co-Authored-By` or "Generated with Claude Code" to commits or PRs.**

### PR Description Template

An empty PR description turns review into a game of telephone. Fill out the
template below in every PR body (drop sections that genuinely don't apply, e.g.
Renders on a pure-CI change). The goal: a reviewer should understand _what_
changed and _why_ without having to ask. WHAT and WHY live in the prose; the
_how_ lives in the diff.

```markdown
## Scope

<!-- Brief description of WHAT you're doing and WHY. The big picture. -->

closes #<issue>

## Implementation

<!-- HOW you achieved it. High-level program flow, any refactor, the tradeoffs
you took, and anything you'd like reviewers to look at especially closely. -->

## Renders / Screenshots

<!-- This is a visual, WYSIWYG-to-the-physical-loom app — show, don't tell.
For ANY change touching the algorithm, render params, or preprocessing, include
the SAME source image rendered before and after at the SAME line count and
settings. That side-by-side is the only reliable way to catch the exact tonal/
quality regressions we keep fighting (see Product Invariants). For UI, show
desktop + mobile. For pure backend/algorithm internals, a flow/diagram or the
relevant numbers is a fine substitute. -->

|         | before | after |
| ------- | ------ | ----- |
| desktop |        |       |
| mobile  |        |       |

## How to Test

<!-- 1) The automated coverage: which unit/integration/e2e tests you added or
updated for the behavior in this PR (no PR merges without them — see Testing).
2) Manual repro: step-by-step to see the change in action, so a reviewer
unfamiliar with this area can verify it. -->

## Invariants & Risk

<!-- Does this touch pin count, max line count, render params, the advisor's
reach, or anything that changes what the on-screen render produces? Confirm the
Product Invariants hold. Call out any settings/migration changes explicitly —
they persist in Supabase and can silently change prod long after merge (a "dead"
setting can come alive when later code wires it). -->

## Emoji Guide

**For reviewers: emojis call out blocking vs. non-blocking feedback.**

| Type         | Emoji          | Meaning                                       |
| ------------ | -------------- | --------------------------------------------- |
| Blocking     | 🔴 ❌ 🚨       | Must be addressed before merge                |
| Non-blocking | 🟡 💡 🤔 💭    | Minor suggestion, nit, or clarifying question |
| Praise       | 🟢 💚 😍 👍 🙌 | Positive feedback — a crucial part of review  |
