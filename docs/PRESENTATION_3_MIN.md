# Three-minute presentation scenario

## Demo story

**A researcher receives an unfamiliar scientific dataset, explores it quickly, and then moves into an explicit review process before producing a derived result.**

Audience: hackathon judges. Format: a live app demo with short narration, not a tour of every control. Approximately 350 spoken words plus clicks; rehearse with a timer and keep the six time boundaries below. The narration is a script, not a promise of exact speaking duration.

## Before presenting — not part of the three minutes

1. Launch **Start Explorer.bat**. Keep the server running; use its actual address, not a memorized port.
2. Download [Palmer Penguins CSV](https://raw.githubusercontent.com/allisonhorst/palmerpenguins/main/inst/extdata/penguins.csv) before the presentation. [Source documentation](https://allisonhorst.github.io/palmerpenguins/) provides attribution and context. Do not rely on venue Wi-Fi.
3. Load it in the Explorer. Set **Scatter plot**, X `flipper_length_mm`, Y `body_mass_g`. In the tested snapshot expect 344 loaded, 342 valid and two omitted rows.
4. Open the reviewed workflow in a second tab. Inspect `examples/reader_data.json` with the outcome “Create a daily summary of valid observations.” Leave genuine unresolved questions unresolved. Prepare this tab before the clock starts.
5. Have the test summary and Bob development evidence available locally as backup. Do not display private task exports or claim current app screenshots show Bob's original session.
6. Do not attempt the entire approval process live in three minutes. Demonstrate its gates; describe saved outputs unless you have independently prepared and verified a labeled demo run.

## 0:00–0:25 — The problem

**Screen:** Explorer, dataset already loaded.

**Say:**

“Opening a scientific file is easy. Knowing what its columns mean, which values are missing, and which processing decisions are justified is harder. We built Scientific Data Explorer to separate those steps: first inspect the data, then review its meaning, then execute a supported workflow with an explicit record of the decisions.”

## 0:25–0:55 — Load and explore

**Action:** Point to the file control and the X/Y selectors; keep the scatter plot visible.

**Say:**

“Here I have the public Palmer Penguins dataset. I select flipper length and body mass, and the app draws a scatter plot directly from the rows. The same interface accepts CSV, TSV, JSON, JSON Lines and SQLite tables. Reading is local, and the original file is not changed. The controls are generic rather than built around this particular dataset.”

## 0:55–1:20 — Make omissions visible

**Action:** Switch Graph to **Histogram**. Point to the valid/omitted counts and briefly to the table.

**Say:**

“Switching to a histogram shows the distribution of body mass. Notice the counts: in this snapshot, two rows lack numeric measurements and are omitted from the chart. Their source values remain in the table. We do not replace missing values with zero or silently convert units. A graph is an exploratory view, not a scientific approval.”

## 1:20–1:55 — Show the reviewed workflow

**Action:** Switch to the pre-inspected workflow tab and show an unresolved question and the review controls. No rushed approvals.

**Say:**

“For processing, we move to the reviewed workflow. The application inventories the source, proposes field meanings, and creates a draft contract. Uncertain units or timestamps become questions for review. Contract approval and processing-step approval are separate. Supported operations include explicit quality filtering, aggregation and export. Before saving, the user checks a calculated preview; saved runs include results and provenance. The Explorer cannot bypass these execution gates.”

## 1:55–2:25 — Explain Bob's role

**Action:** Show the development-record heading or keep the layered workflow visible.

**Say:**

“IBM Bob helped build the layered discovery and planning system, the initial browser interface, and a scientific adapter extension. We used saved task history to document that contribution. After the Bob session, Codex added further safety repairs, bounded execution and this simplified chart interface. Bob was a development tool here; the running app does not require a live Bob connection.”

## 2:25–3:00 — Evidence, limits and close

**Action:** Show the verification summary, then return to the Explorer.

**Say:**

“The packaged build passed 182 software tests and all 27 original scientific checks. We tested multiple public scientific sources and native SQLite tables. SQLite is the only database engine tested so far; this is not universal database support or scientific certification. The next step is adding more connectors and explicit nested-field mapping. The result is a small local tool for exploring unfamiliar data and making processing decisions inspectable.”

## If something goes wrong

- **Download fails:** use the CSV saved before presenting. If unavailable, switch to the included synthetic `examples/reader_data.json`; do not repeat the penguin counts or call it real field data.
- **Browser/API fails:** show a previously captured screenshot, explicitly calling it a screenshot from an earlier run. Do not imply a live operation succeeded.
- **A workflow remains blocked:** say “This is unresolved metadata; the program requires a decision before execution.” Do not invent evidence to approve it.
- **You are behind time:** skip the table scroll and show only the histogram counts. Keep the attribution and limitations.

## Likely questions — short answers

**Does Bob run the workflow?** No. Bob contributed to development. The local Python application runs the implemented operations.

**Does it work with any database?** No. The design is extensible, but tested database-engine support is SQLite. The other supported inputs are file formats.

**Does a chart prove the data are valid?** No. It visualizes eligible numeric cells and discloses omissions. Scientific interpretation and QC decisions need separate evidence and review.

**What leaves my computer?** The core app reads locally. Explorer uploads go to the loopback server, not a cloud service. External documentation links use the internet.

**Is the approval secure for a regulated team?** This prototype records declared decisions, not authenticated or tamper-evident institutional approvals.

**Where is the evidence?** The project retains source hashes, test reports and development history. Those histories and private datasets are deliberately not bundled into the lightweight application ZIP.
