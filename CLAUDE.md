# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

A virtual 2-station assembly-line quality simulator (Korean UI). Users set production conditions (temperature, head speed) and a box count, then watch a synced SVG animation of two screw-fastening machines process units. Every fastening event generates a measurement written to a real `.xlsx` file; out-of-spec values are flagged NG. On lot completion, a Python-aggregated report with an LLM-generated interpretation (split into analysis + recommendation) is produced, and two completed lots can be compared side by side.

The full spec lives in `가상조립라인_프로젝트명세서.md.pdf` (Korean, v3). It defines a 5-phase build order (CLI logic → FastAPI → frontend/animation → compare UI → visual polish) — follow that phase order for any large rework, verifying each phase by actually running it before moving to the next. **`SPEC_CHANGES.md` is a required companion read**: it's a v3→v3.1 delta doc (rail-speed removal, per-unit excel rows, custom save paths, head/screw alignment, feeder clip animation, AI comment split) written because the spec itself is a PDF this tooling can't edit in place. Where the two disagree, `SPEC_CHANGES.md` wins.

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
python pipeline_test.py <boxes> --temp <20-30> --head <느림|보통|빠름>
# e.g. python pipeline_test.py 2 --temp 29 --head 빠름
```

Excel and HTML report output land in `config.EXCEL_DIR` / `config.REPORT_DIR` — relative paths under this repo's own folder (`./엑셀 데이터`, `./보고서`), not `./output`. `./output` now holds only `lots_index.json` (internal data, not a user-facing artifact). All three directories are created on demand (`main.py` at startup, `ExcelWriter`/`report.generate_report` lazily), so a clean checkout works with no manual `mkdir` — and, being relative, works unmodified regardless of OS or where the repo is cloned, as long as the server is started from the project root.

There is no automated test suite (no pytest). Verification is done by actually running the server/CLI and inspecting the generated `.xlsx`/`.html` output, plus ad hoc Playwright scripts for the frontend (browser automation isn't wired into a checked-in test — write throwaway scripts to a scratch dir when verifying UI/timing behavior).

**Windows console gotcha**: `pipeline_test.py` reconfigures stdout to UTF-8 itself. If you write other one-off scripts that print Korean text, either add `sys.stdout.reconfigure(encoding="utf-8")` or run with `PYTHONIOENCODING=utf-8`, or the terminal will mangle the output (the underlying data/files are still correct UTF-8 either way).

### LLM setup

Copy `.env.example` to `.env` and set `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY` to a real OpenAI-compatible endpoint. Note: if the backing server is **Ollama**, its native chat API lives at `/api/chat`, but this project's `llm_client.py` uses the `openai` SDK, so `LLM_BASE_URL` must point at Ollama's OpenAI-compatibility path (`http://host:11434/v1`), not `/api/chat`. Without a configured LLM, every AI-comment call fails gracefully and the report shows "AI 코멘트 생성 실패" instead — this is expected/by-design (see F6 in the spec), not a bug.

## Architecture

### Shared domain modules, two entry points

The core domain logic is factored into standalone modules that **both** `pipeline_test.py` (CLI) and `main.py` (FastAPI) call — there is exactly one implementation of measurement generation, lot state, excel writing, and report building, not one per entry point:

- `config.py` — every tunable constant (box size, spec limits, temperature/speed effect factors, tact timing bases, file paths, LLM env vars). `config.tact_times(head_speed)` is the **only** place tact-time scaling is computed; the frontend never recomputes it, it just uses the values the `/api/lot` response hands it. Rail/conveyor speed was removed as a production condition — `index_sec` in the returned dict is always the fixed `INDEX_SEC`.
- `measurement.py` — `generate_measurement(station, temperature, head_speed)` implements the condition→measurement-distribution formula (temperature biases the mean, head speed scales the std-dev).
- `lot_manager.py` — `Lot` dataclass owns all in-flight state for one production run (units, per-station judgments, NG events) and exposes `Lot.aggregate()`, which is the single source of truth for every summary number that later shows up in the Excel "Lot요약" sheet, the HTML report, `lots_index.json`, and the status API — if you need a new summary stat, add it here once, not in three places. `lot_manager.next_lot_id()` derives the day's next `LOT-YYYYMMDD-NNN` by scanning `config.EXCEL_DIR` (not `OUTPUT_DIR`) for existing `.xlsx` files — if excel output ever moves again, this scan target must move with it or lot numbering silently resets.
- `excel_writer.py` — `ExcelWriter` holds the `openpyxl` workbook **in memory** for the life of a lot, saved to `config.EXCEL_DIR` (on this repo's original machine that resolves under an OneDrive-synced folder — expect occasional save failures from the sync client locking the file; this class of failure isn't OneDrive-specific, so the retry logic applies regardless of where the project lives). `wb.save()` is retried on every write; if it fails the exception is swallowed and logged — nothing is lost because the in-memory workbook itself is the retry queue, and the next successful save flushes everything accumulated since. The "측정기록" sheet is **one row per unit (SN)**, not per measurement event: `append_measurement(sn, station, value, judgment, ts)` creates the row on the first station measured for that SN and fills in the other station's columns on the second call (order-independent), computing 최종판정 only once both are present. LSL/USL are written once in row 1 as an informational spec line, not repeated per row — column headers are row 2, data starts row 3.
- `report.py` — turns an `aggregate()` dict into the lot HTML report (saved to `config.REPORT_DIR`), calls the LLM for the interpretation comment, and appends the completed lot's condition+aggregate summary to `output/lots_index.json` (this file is what makes the compare feature work across server restarts — completed lots don't need to still be in server memory; it also deliberately stays under `./output`, separate from the user-facing `EXCEL_DIR`/`REPORT_DIR`, since it's internal data). `report.render_ai_comment_block(comment)` is the shared renderer both `report.py` and `compare.py` use for the analysis paragraph + optional highlighted recommendation box — don't duplicate this markup.
- `compare.py` — reads two entries from `lots_index.json` and builds the 3-layer compare report (saved to `config.REPORT_DIR`): a Python numeric table, a Python rule-based conclusion sentence (no LLM), then an LLM interpretation via the same analysis/recommendation split. Numbers shown anywhere in reports always come from Python aggregation; the LLM is only ever asked to interpret numbers it's given, never to produce them. Old `lots_index.json` entries from before a schema change (e.g. entries that still have a `conveyor_speed` key) must keep working here — code should only ever read keys it still cares about, never assume the absence of stale extra keys is an error.
- `llm_client.py` — wraps the `openai` SDK client. The system prompts require the model to answer as `{"analysis": "...", "recommendation": "..."}` JSON only; `_parse_structured()` strips markdown code fences defensively and falls back to treating the whole response as `analysis` with `recommendation: None` if JSON parsing fails or either field is empty — this fallback (not an exception) is what callers see, so `report.render_ai_comment_block` must handle `recommendation: None` by simply omitting the recommendation box. Every call path (missing config, request failure, bad JSON) degrades gracefully instead of raising, so a down/misconfigured LLM never breaks lot completion or report generation.

`main.py` additionally keeps an in-memory `ACTIVE_LOTS: dict[lot_id, LotSession]` (a `Lot` + its `ExcelWriter` + report-generation flags) for lots currently in progress; the Excel/report files on disk (not this dict) are the durable record.

### Frontend: single state-machine drives both heads

`static/app.js`'s `LineEngine` class is the one authority for line state — it is a single `requestAnimationFrame` loop cycling through `DOWN → FASTEN → UP → INDEX` phases; both machine heads (`#headM1`, `#headM2`) just read the engine's current phase/progress and render their Y position from it every frame. There are deliberately **not** two independent per-head timers — that would risk visual desync, which the spec treats as a correctness bug, not a cosmetic one.

Line "slots" are modeled as a 4-element array `[IN, ST1, MID, ST2]`; entry (from the feeder) and exit (into the cart) are handled as transitions in/out of that array during the `INDEX` phase, not as separate slots. Measurement calls (`POST /api/measure`) fire exactly once per station per unit, at the instant `DOWN` phase completes (simulated contact) — only for slots that are actually occupied, so idle stations "punch" with no side effects.

Tact durations always come from the `tact_times` object returned by `POST /api/lot` (already scaled by `config.tact_times`) — never hardcode or recompute timing scale factors in `app.js`.

**Head X position and screw position share one constant (`SCREW_OFFSET_X` in `app.js`), by design.** The two machines are no longer pixel-identical: base/column stay centered on their slot for both, but each head is horizontally offset from slot center toward the screw point it fastens (ST1 head left, ST2 head right — a deliberate, spec-sanctioned exception to "machines look identical," connected visually by a small mount-arm rect). `SCREW_OFFSET_X` is computed once from `UNIT_TOP_BAR_WIDTH`/`SCREW_INSET_RATIO` and used for both the screw-mark local position (in `createUnitGroup`) and the head's X anchor (`HEAD_M1_X`/`HEAD_M2_X`) — if you ever touch unit dimensions or the 20%/80% screw-inset rule, change it in that one place; don't hand-tune head X and screw X separately or they will drift apart again.

**Feeder entrance uses an SVG clip, not a raw spawn.** A newly spawned unit gets `clip-path="url(#feederClip)"` (defined in `index.html`, boundary at x=100) permanently in `createUnitGroup` — harmless once the unit reaches its resting slots since every resting position is well to the right of x=100, but critical during the entrance animation, where it hides the unit until it's slid past the gate. `FEEDER_X` is deliberately set to `SLOT_X[0] - 150` (i.e. the *same* 150px pitch every other slot-to-slot transition uses), not an arbitrary short distance — that was the actual fix for two units visually overlapping momentarily (a too-short feeder-to-IN distance let the newly spawned unit's start position spatially coincide with the outgoing IN-slot unit's position at the start of the same INDEX phase). If you change slot pitch, keep `FEEDER_X` and the clip boundary consistent with it or the overlap bug will return.

**CSS gotcha already fixed once**: don't add unconditional `display: ...` rules for elements that are toggled via the HTML `hidden` attribute — an author-stylesheet `display` rule silently overrides the UA default `[hidden] { display: none }` regardless of selector specificity (author styles always beat UA styles). `style.css` has a global `[hidden] { display: none !important; }` guarding against this; keep it if you add more `hidden`-toggled elements.

### API surface (`main.py`)

`POST /api/lot` (body: `{boxes, temperature, head_speed}` — no `conveyor_speed`), `POST /api/measure`, `POST /api/unit-complete`, `GET /api/status/{lot_id}`, `GET /api/report/{lot_id}`, `GET /api/lots`, `GET /api/compare?lot_a=&lot_b=`, plus `GET /` and static mounts at `/static` and `/excel-files` (the latter serves `config.EXCEL_DIR` and is how report pages link to their `.xlsx` download — `report.py`'s download `href` and this mount's path prefix must stay in sync). `GET /api/report/{lot_id}` reads the rendered HTML directly from `config.REPORT_DIR` rather than through a static mount. A global exception handler returns `500 {"error": ...}` JSON for anything unhandled — API calls are expected to never take the server down, matching the spec's resilience requirements.
