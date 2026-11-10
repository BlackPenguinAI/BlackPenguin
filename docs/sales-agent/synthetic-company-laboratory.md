# Synthetic Company / three-Project sales laboratory

Requires the previous Current Turn Refinement delivery. No production tenant or
lead is created. The Company and all three Projects exist together in a private,
disposable SQLite worker, using the current coordinator, memory, planner, tools,
composition and in-app effect receipts. No alternate toy sales agent is used.

## Fixture matrix

Company: **SYNTHETIC - Penguin Sales Laboratory**.
All prices are fictional USD amounts. Areas are square metres.

| Project | Property type | Beds / baths | Area | Starting price | Quantity | Gallery | PDF |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Harbor Gardens | Bay Residence | 4 / 3 | 240 | 780000 | 3 | Yes | Yes |
| Cedar Heights | Cedar Loft | 2 / 2 | 110 | 325000 | 5 | Yes | No |
| Cedar Heights | Cedar Studio | 1 / 1 | 52 | 210000 | 2 | No | Yes |
| Sierra Commons | Ridge Townhome | 3 / 2.5 | 165 | 460000 | 4 | No | No |
| Sierra Commons | Summit Villa | 4 / 3 | 220 | 620000 | 0 | Yes | Yes |
| Sierra Commons | Valley Apartment | 2 / 2 | 95 | Unknown | Unknown | No | No |

All names shown to the agent include SYNTHETIC on the Project. Actual gallery
snapshots embed two decodable PNG illustrations each. They are explicitly marked
as synthetic, not real architecture photos. Actual single-page PDFs contain only
that property's approved facts. Brochures have brochure coverage only, not photos
or floor-plan coverage. A file extension never grants additional coverage.
Resource creation, validation and approval use the existing production services,
against the private database and private storage. Published Project snapshots are
created through the current onboarding approval service. No new dependencies.

## Nine adaptive dialogues

Three independently created new leads per Project:

1. **new_buyer:** available types and price, then bedrooms/area and qualification.
2. **targeted_materials:** photos and a PDF for a specific property; accept an exact
   relevant offer, accept a genuine absence without requesting substitutes; parking.
3. **continuity:** price/availability, a cash declaration and any needed correction,
   then explicit change to bank financing combined with a bedroom question.

The buyer is an LLM, not a fixed list of lead messages. It receives its initial
fictional profile and goals plus only the customer-visible transcript. It does not
receive the database, true asset availability, expected answers or private traces.
It generates one short message at a time and responds to the actual agent reply.
A separate lead model may be selected with `--lead-model`; the sales model remains
exactly the currently published platform configuration.

The resources scenario covers both resources, PDF only and no resources across the
three Projects. The catalog includes gallery-only stock, unknown facts and a sold-
out property for broader/ad hoc follow-up scenarios. This initial suite does not
claim every possible property/goal combination has been exercised. Add scenarios
or rerun with new wording after reviewing the reports; no prompts self-publish.

Deterministic checks audit current workflow, interpretation/composition acceptance,
customer-visible receipts, no internal processing narration, no transport/calendar
side effects, minimum dialogue length and actual exercised goals. Material cases
require the available requested resources to have real sandbox share receipts and
reject cross-Project or unrequested-property shares. The driver saying `done` is
not by itself success. Traces retain the actual interpreted facts and responses.

The optional `--judge` uses the existing advisory semantic judge. It is disabled
by default because its earlier scores required calibration. A machine PASS proves
these assertions, not complete factual/natural sales quality; inspect the replies.
Calendar scheduling and WhatsApp/SMS provider delivery are outside this suite.
The buyer LLM does not open resource URLs or inspect images/PDF pages. Resource
checks inspect local bytes, approved coverage, scope and share receipts; public
browser rendering remains covered by separate resource-route/UI tests.

## Prepare with zero inference

This generates and approves all fixtures and resources without reading the source
database, loading a model credential or making model calls. Useful for local/CI:

```bash
python -m tools.sales_ai.synthetic_lab --prepare-only --output /tmp/sales-lab-prepared-1
```

Run from backend locally, or in the server container:

```bash
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
  --prepare-only --output /tmp/sales-lab-prepared-1
```

`PREPARED` is not an agent quality result.

## Run the actual LLM lead against the current Sales engine

After deploying this delivery, run over SSH:

```bash
docker exec -i -w /app bp_api_prod python -m tools.sales_ai.synthetic_lab \
  --configuration-id cbc8abfa-23d3-417c-97dd-fd12e3406ed4 \
  --max-calls 180 --max-turns 6 \
  --output /tmp/sales-synthetic-lab-1

docker cp bp_api_prod:/tmp/sales-synthetic-lab-1/synthetic-sales-results.zip ./sales-synthetic-lab-1.zip
```

Use a new empty output directory each run. The inference cap is **global across
all three Projects**, includes buyer, sales, repair and optional judge calls, and
is divided fairly among Projects. It is not a dollar spending cap. Stop or turn
limits may leave goals incomplete; reports expose failures rather than pretending
success. Use `--max-turns 8 --max-calls 240` for longer dialogues if needed.

Production access reads only the selected global Sales configuration, its one
published version and credential, in a read-only transaction. No production
Company profile, Project, lead, message, calendar or messaging credential is copied.
The temporary credential input is private and removed when the worker finishes.
The export includes no SQLite database, option/credential file or usable live URL.
OpenRouter inference consumes the configured account's credit. No live LLM calls
were made while preparing this delivery.

Download using Windows PowerShell:

```powershell
& "$env:WINDIR\System32\OpenSSH\scp.exe" jorge@206.189.118.99:~/sales-synthetic-lab-1.zip "$env:USERPROFILE\Downloads\sales-synthetic-lab-1.zip"
```

Send this ZIP back for analysis. It contains:

- `summary.json`: global status, counts, usage/cost if supplied, per-Project results.
- `catalog.json`: complete synthetic ground truth and resource checksums.
- `harbor/report.json` and `.md`, likewise `cedar` and `sierra`: transcripts,
  interpretation attempts, planning/composition traces, profiles and assertions.
- `materials/`: readable local PDF and gallery copies for inspection.

The records are **not added to the production UI** and do not affect subscriptions,
reporting, live leads, transport outboxes or real appointment calendars.

## First discovered regression

The actual engine integration test exposed its English courtesy continuation
"You can message here if another question comes up." being classified as French.
This delivery adds the missing ordinary English courtesy words to the existing
lexical language gate, with regression tests for acknowledgement and farewell.
It does not disable non-English input/output controls.

## Local validation

162 offline tests passed, including the new real-engine integration through all
nine dialogues (27 agent turns), existing evaluation isolation, current-flow
regressions, exact evidence/recovery and composition checks. The provider boundary
was scripted; this does not constitute a live LLM quality run.
