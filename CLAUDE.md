# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

A virtual 2-station assembly-line quality simulator (Korean UI). Users set production conditions (temperature, head speed, rail speed) and a box count, then watch a synced SVG animation of two screw-fastening machines process units. Every fastening event generates a measurement written to a real `.xlsx` file; out-of-spec values are flagged NG. On lot completion, a Python-aggregated report with an LLM-generated interpretation comment is produced, and two completed lots can be compared side by side.

The full spec lives in `가상조립라인_프로젝트명세서.md.pdf` (Korean). It defines a 5-phase build order (CLI logic → FastAPI → frontend/animation → compare UI → visual polish) — follow that phase order for any large rework, verifying each phase by actually running it before moving to the next.

## Commands

```bash
# setup (Windows / git-bash)
python -m venv venv
source venv/Scripts/activate
pip install -r requirements.txt

# run the web app
uvicorn main:app --reload
# → http://127.0.0.1:8000

# run the core pipeline without the web layer (CLI, useful for testing the
# measurement/excel/report logic in isolation)
python pipeline_test.py <boxes> --temp <20-30> --head <느림|보통|빠름> --conveyor <느림|보통|빠름>
# e.g. python pipeline_test.py 2 --temp 29 --head 빠름 --conveyor 보통
```

There is no automated test suite (no pytest). Verification is done by actually running the server/CLI and inspecting the generated `.xlsx`/`.html` output, plus ad hoc Playwright scripts for the frontend (browser automation isn't wired into a checked-in test — write throwaway scripts to a scratch dir when verifying UI/timing behavior).

**Windows console gotcha**: `pipeline_test.py` reconfigures stdout to UTF-8 itself. If you write other one-off scripts that print Korean text, either add `sys.stdout.reconfigure(encoding="utf-8")` or run with `PYTHONIOENCODING=utf-8`, or the terminal will mangle the output (the underlying data/files are still correct UTF-8 either way).

### LLM setup

Copy `.env.example` to `.env` and set `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY` to a real OpenAI-compatible endpoint. Note: if the backing server is **Ollama**, its native chat API lives at `/api/chat`, but this project's `llm_client.py` uses the `openai` SDK, so `LLM_BASE_URL` must point at Ollama's OpenAI-compatibility path (`http://host:11434/v1`), not `/api/chat`. Without a configured LLM, every AI-comment call fails gracefully and the report shows "AI 코멘트 생성 실패" instead — this is expected/by-design (see F6 in the spec), not a bug.

## Architecture

### Shared domain modules, two entry points

The core domain logic is factored into standalone modules that **both** `pipeline_test.py` (CLI) and `main.py` (FastAPI) call — there is exactly one implementation of measurement generation, lot state, excel writing, and report building, not one per entry point:

- `config.py` — every tunable constant (box size, spec limits, temperature/speed effect factors, tact timing bases, file paths, LLM env vars). `config.tact_times(head_speed, conveyor_speed)` is the **only** place tact-time scaling is computed; the frontend never recomputes it, it just uses the values the `/api/lot` response hands it.
- `measurement.py` — `generate_measurement(station, temperature, head_speed)` implements the condition→measurement-distribution formula (temperature biases the mean, head speed scales the std-dev).
- `lot_manager.py` — `Lot` dataclass owns all in-flight state for one production run (units, per-station judgments, NG events) and exposes `Lot.aggregate()`, which is the single source of truth for every summary number that later shows up in the Excel "Lot요약" sheet, the HTML report, `lots_index.json`, and the status API — if you need a new summary stat, add it here once, not in three places.
- `excel_writer.py` — `ExcelWriter` holds the `openpyxl` workbook **in memory** for the life of a lot; `wb.save()` is retried on every write. If a save fails (e.g. file locked by Excel), the exception is swallowed and logged — nothing is lost because the in-memory workbook itself is the retry queue; the next successful save flushes everything accumulated since the last failure.
- `report.py` — turns an `aggregate()` dict into the lot HTML report, calls the LLM for the interpretation comment, and appends the completed lot's condition+aggregate summary to `output/lots_index.json` (this file is what makes the compare feature work across server restarts — completed lots don't need to still be in server memory).
- `compare.py` — reads two entries from `lots_index.json` and builds the 3-layer compare report: a Python numeric table, a Python rule-based conclusion sentence (no LLM), then an LLM interpretation. Numbers shown anywhere in reports always come from Python aggregation; the LLM is only ever asked to interpret numbers it's given, never to produce them.
- `llm_client.py` — wraps the `openai` SDK client; every call path degrades to a fixed failure string instead of raising, so a down/misconfigured LLM never breaks lot completion or report generation.

`main.py` additionally keeps an in-memory `ACTIVE_LOTS: dict[lot_id, LotSession]` (a `Lot` + its `ExcelWriter` + report-generation flags) for lots currently in progress; the Excel/report files on disk (not this dict) are the durable record.

### Frontend: single state-machine drives both heads

`static/app.js`'s `LineEngine` class is the one authority for line state — it is a single `requestAnimationFrame` loop cycling through `DOWN → FASTEN → UP → INDEX` phases; both machine heads (`#headM1`, `#headM2`) just read the engine's current phase/progress and render their Y position from it every frame. There are deliberately **not** two independent per-head timers — that would risk visual desync, which the spec treats as a correctness bug, not a cosmetic one.

Line "slots" are modeled as a 4-element array `[IN, ST1, MID, ST2]`; entry (from the feeder) and exit (into the cart) are handled as transitions in/out of that array during the `INDEX` phase, not as separate slots. Measurement calls (`POST /api/measure`) fire exactly once per station per unit, at the instant `DOWN` phase completes (simulated contact) — only for slots that are actually occupied, so idle stations "punch" with no side effects.

Tact durations always come from the `tact_times` object returned by `POST /api/lot` (already scaled by `config.tact_times`) — never hardcode or recompute timing scale factors in `app.js`.

**CSS gotcha already fixed once**: don't add unconditional `display: ...` rules for elements that are toggled via the HTML `hidden` attribute — an author-stylesheet `display` rule silently overrides the UA default `[hidden] { display: none }` regardless of selector specificity (author styles always beat UA styles). `style.css` has a global `[hidden] { display: none !important; }` guarding against this; keep it if you add more `hidden`-toggled elements.

### API surface (`main.py`)

`POST /api/lot`, `POST /api/measure`, `POST /api/unit-complete`, `GET /api/status/{lot_id}`, `GET /api/report/{lot_id}`, `GET /api/lots`, `GET /api/compare?lot_a=&lot_b=`, plus `GET /` and static mounts at `/static` and `/output` (the latter is how report pages link to their `.xlsx` download and how `/api/report/{lot_id}` resolves an already-rendered HTML file on disk). A global exception handler returns `500 {"error": ...}` JSON for anything unhandled — API calls are expected to never take the server down, matching the spec's resilience requirements.
