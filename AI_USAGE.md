# How AI was used

The brief asks to see the prompts and the harness behind this submission, so this file covers two
separate things:

1. **The prompts inside the product**, which the assistant sends to an LLM at runtime.
2. **The AI coding assistant** (Claude Code in VS Code), which helped write and fix the code,
   including the build prompts.

In between, a short section explains how the data was prepared and used, because that is where most
of the design effort went.

The first matters more. Those prompts are part of the system design, and they are what a reviewer can
run and test.

---

## 1. Prompts inside the product

All runtime prompts are in [`backend/app/prompts.py`](backend/app/prompts.py) and are versioned by
`PROMPT_VERSION`. Every audit-log record stores the prompt version, so you can always tell which
version produced an answer.

### Design: two narrow calls, not one broad one

| Step | Prompt | The model's only job | What it never does |
|---|---|---|---|
| Plan | `PLANNER_SYSTEM` | Pick a route (`data` / `policy` / `both` / `none`), tool parameters and the policy clause ids | Answer the question or calculate |
| Compose | `COMPOSER_SYSTEM` + `COMPOSER_USER` | Turn the evidence that code computed into short prose, and say what it cited | Make up, round or derive figures |

A single "here is the CSV and the policy, answer this" prompt would have been faster to write. For a
financial-controls tool it would have been the wrong call: a figure that is wrong but looks
authoritative is the worst failure, and the most likely source of one is an LLM doing arithmetic over
140 rows in three currencies. Splitting the work means the model makes judgements (what is being
asked, which clause applies) and code does everything that can be checked.

### Prompt decisions and why

- **Routing first, with `none` as a valid outcome.** Declining is part of the planner's output, so
  "I can't answer that from this data" is a planned result, not an exception. The planner prompt
  lists the fields that do not exist (payment status, approver roles, requesters, credit-note links)
  and says to choose `none` "rather than an approximation". Most finance hallucinations I'd expect come
  from the model filling in a field that isn't there, such as "paid" or "approved by the CFO".
- **Policy in context, no retrieval.** The policy is about 50 lines, so it goes into both system
  prompts in full, inside `<policy>` tags. A vector store would add a failure mode (a missed chunk)
  with no benefit at this size. Clause ids are checked against the parsed policy, so a citation to a
  section that doesn't exist is rejected.
- **Domain rules written as prompt rules**, because they are where a general model goes wrong:
  "spend" means net of credit notes; spend is invoiced, not "paid"; a named approver can't be
  assumed to hold a role; the PO threshold is EUR 1,000 (§2.1).
- **Prompt-injection stance.** Both prompts say the question and the evidence are untrusted data,
  not instructions. The real protection is structural, though: the tools are typed and read-only,
  so a successful injection can at most choose a wrong filter, which the analyst can see in the
  evidence.
- **Structured output by schema, not by asking nicely.** For Anthropic, the output schema is a forced
  tool call (`tool_choice`). For Ollama, it's `format: <json schema>` with temperature 0. In both cases
  the result is validated with Pydantic ([`llm.py`](backend/app/llm.py),
  [`pipeline_types.py`](backend/app/pipeline_types.py)).
- **Retries pass back the specific rejection reason** (`RETRY_SUFFIX`), such as "Figures not in
  evidence: 1131083". A generic "try again" rarely works. One retry, then a fallback.
- **Reasoning is shown to the user.** The planner's `reasoning` field is written for the analyst
  ("one or two plain sentences"), so the UI can show why it went to the data, the policy or both.

### What checks the model's output

[`grounding.py`](backend/app/grounding.py) runs on every composed answer. It rejects any number,
invoice id, clause reference or evidence id that isn't in the evidence, the policy or the question.
After one failed retry, the answer is replaced with the deterministic template. The response says
which source produced it (`answer_source: llm | template`), so the swap is never hidden.

There is a known limitation: this check proves a number *exists* in the evidence, not that it is
used *correctly* (for example, vendor A's total attributed to vendor B). That gap is why the
evaluation plan in the README includes claim-level judging and sampled human review.

### What has and hasn't been tested

The submission runs in **stub mode** (`LLM_PROVIDER=stub`): a rule-based planner plus template
answers, labelled as such in the API and the UI. The prompts above are wired up, and the
Anthropic and Ollama clients are covered by tests with mocked transports. **The prompts have not been
tuned against a live model.** That is the first item in "next steps". I'd rather say so than present
untested prompt engineering as tuned.

---

## How the data was prepared and used

**No cleaning, on purpose.** The brief says the data is clean and that the missing POs, missing
approvers and non-active vendors are intentional. "Cleaning" them, by dropping rows or imputing
values, would hide exactly the control failures a Finance analyst needs to see. So the data is
**validated and enriched, never altered**. All of this happens once at startup, in
[`data.py`](backend/app/data.py).

| Step | What happens | Why |
|---|---|---|
| Load | Both CSVs are read with `keep_default_na=False` | A blank PO or approver stays `""`, so "missing" is explicit and testable, never a NaN that silently falls out of a filter |
| Trace | Each invoice gets `source_line`, its line number in the CSV | Every figure on screen can be traced back to a row in the source file (§8.2) |
| Join | Invoices are joined to the vendor master with `validate="many_to_one"`. Startup fails if an invoice's vendor is missing | A duplicate or unknown vendor would corrupt every total, so it fails loudly rather than producing a wrong answer quietly |
| Convert | Each invoice is converted to EUR with an ECB rate on its invoice date (§5.1), or the 2025 annual average labelled "indicative" if daily rates haven't been fetched. Weekend dates use the last published rate | Summing EUR, GBP and USD in their own currencies is meaningless. The FX mode is shown on every answer |
| Round | `amount_eur` is rounded to cents per invoice | The evidence rows add up exactly to the reported total, so an analyst can reconcile it |
| Derive | `month` and `quarter` | Time-based questions |
| Version | A SHA-256 of the CSVs, the policy and the FX file gives a `data_version` | Each answer and audit record says exactly which data produced it |

**How the data is interpreted:**
- **Credit notes** are invoices with a negative amount. "Spend" is net of credit notes; gross is
  reported too. The approval band for a credit note uses its absolute value (an assumption flagged for
  Finance to confirm).
- **Control flags** are computed by code, not the model: missing PO only at or above EUR 1,000 (§2.1,
  §2.2), missing approver (§3.1), and vendor not `ACTIVE` (§4.1). Flagged invoices stay in spend,
  because they were invoiced, but the flags appear next to the figure.
- **Gaps in the data are reported, never guessed.** There is no role directory, requester, payment
  status or credit-note link, so approver authority, segregation of duties (§7.1) and credit-note
  matching come back as `cannot_verify`.
- **The policy** is parsed into clauses with line numbers, and the approval table into bands
  ([`policy.py`](backend/app/policy.py)). The model only cites clause ids; the quoted text is looked
  up from the file, so a quote can't be invented.
- **`/summary` uses no LLM.** It's computed directly from the data
  ([`summary.py`](backend/app/summary.py)). Native-currency totals are left out of the vendor-status
  breakdown, because they would mix currencies.

---

## 2. AI coding assistant

**Tool:** Claude Code (VS Code extension).
**How I worked with it:** in short, task-sized prompts (below). Each change was accepted only if the
test suite passed. The suite includes tests that check the brief's example questions against an
independent recalculation (plain `csv` module, separate from the app's pandas code), so "looks right" was never the bar.

### Build prompts (reconstructed)

The log of the original build session isn't available, so these are **reconstructed from the
delivered code**. They show the order and the intent of the build, not my exact wording. Each step
was a separate prompt, reviewed and tested before the next one.

| # | Prompt | What it produced |
|---|---|---|
| 1 | "Read the brief, the two CSVs and the policy. Before writing any code, list every ambiguity that changes a number (currencies, credit notes, missing PO or approver, non-active vendors) and propose a decision for each, with the policy clause it relies on." | The data decisions table in the README. This was the most important step: the decisions came before the code. |
| 2 | "Build a data layer in pandas that loads both CSVs once, joins invoices to the vendor master and fails loudly on unknown or duplicate vendors. Keep blanks as blanks, not NaN. Add the CSV line number, the FX rate and the EUR amount to every row, and hash the source files into a data version." | [`data.py`](backend/app/data.py) |
| 3 | "Parse the policy markdown into citable clauses with line numbers, and parse the approval table into bands, so code applies the thresholds and the policy stays the single source of truth." | [`policy.py`](backend/app/policy.py) |
| 4 | "Expose the data to the LLM only through typed, read-only tools with strict Pydantic schemas: `query_invoices` (filters, group-by, top-N), `check_invoice` (per-invoice control checks) and `required_approver`. Code does all arithmetic. Controls the data can't prove must return `cannot_verify`, never `pass`." | [`tools.py`](backend/app/tools.py) |
| 5 | "Build a plan → execute → compose → check pipeline. The planner picks a route (data / policy / both / none) and tool calls; the composer writes prose from the evidence only. Validate both against schemas, retry once with the specific rejection reason, and fall back to a labelled template. Write an audit record for every question." | [`pipeline.py`](backend/app/pipeline.py), [`prompts.py`](backend/app/prompts.py), [`grounding.py`](backend/app/grounding.py) |
| 6 | "Add a clearly labelled rule-based stub planner, so the app runs without an API key, plus Anthropic and Ollama clients behind one interface. An LLM outage must return a retryable 503, never a silent switch to the stub." | [`stub.py`](backend/app/stub.py), [`llm.py`](backend/app/llm.py) |
| 7 | "Expose `POST /ask` and `GET /summary` in FastAPI with a consistent error contract. The summary must be computed from data with no LLM involved." | [`main.py`](backend/app/main.py), [`summary.py`](backend/app/summary.py) |
| 8 | "Write tests that recompute the expected figures independently with the `csv` module, cover approval bands at the exact thresholds, and prove hallucinated figures and clauses are rejected." | [`test_backend.py`](backend/tests/test_backend.py) |
| 9 | "Build the React frontend: a summary panel that loads on startup, and a chat panel with explicit loading, error and retry states. Show each answer with its route, reasoning, policy quotes, source rows with CSV line numbers, and caveats." | [`frontend/src/`](frontend/src/) |
| 10 | "Write the README: setup, the architecture, the data decisions, and the write-up on scope, evaluation and production." | [`README.md`](README.md) |

### Session prompts

These come from the session logs. My original prompts were short and informal, so they are edited
here for clarity; the intent and order are unchanged.

**Session 1 (2026-11-04): verification, correctness fixes, UI**

| Prompt | Why / what I checked afterwards |
|---|---|
| "Run a smoke test of the backend and frontend, and add a one-click script to start the app." | Both servers start, `/summary` and `/ask` respond, and there is a launcher (`run_app.bat`) |
| "Rework the UI into a familiar chat layout, with each answer's evidence attached to it." | The evidence stays visually tied to the answer it supports |
| "Some answers are wrong. Re-check them against the data and fix the root cause." | Some answers were wrong, which is the failure this product exists to prevent. Fixed, then re-run against the independent-calculation tests |
| "Clean up the UI and fix the font sizes for readability." | Readability |

**Session 2 (2026-11-04): requirements check and shipping**

| Prompt | Why / what I checked afterwards |
|---|---|
| "Check the submission against every requirement in the brief" (with the brief attached as a PDF) | A line-by-line check against the brief. It found three gaps: no public repo, time spent not filled in, and this file |
| "Create a public GitHub repository and push the project." | Before pushing, a secrets scan and a check that `.env` and `logs/` are git-ignored |
| "Write the AI-usage section and the time-spent note from the perspective of a senior AI/ML engineer." | This file and the time note in the README |

### Lesson

The one real correctness problem during development ("getting wrong answers") was a confident but
wrong answer. That is the same failure an LLM finance assistant is most likely to produce, and it's
why this design keeps arithmetic in tested code and makes every answer show its evidence.

### Verification harness

- `cd backend && python -m pytest` (45 tests), including:
  - the Spain total and the top-5 ranking against an independent calculation, and evidence rows
    that add up to the reported totals;
  - approval bands at the exact thresholds;
  - every clause quote being verbatim from the policy;
  - a hallucinated figure being retried and then replaced by the template;
  - an LLM outage still returning the computed answer;
  - a plan citing a clause that doesn't exist being rejected;
  - unanswerable questions being declined with no evidence;
  - the provider clients (mocked) and the API error contract.
- `logs/audit.jsonl` (git-ignored) records the plan, evidence and versions for each question.
