# Scientific Discovery — Quick User Manual

## What it does

Scientific Discovery reads a local dataset, identifies its fields, proposes their meanings and units, and highlights missing or uncertain information. It collects these interpretations in a **data contract**: a description of how the data should be understood. After you review that contract, it proposes processing steps and can execute supported workflows after you approve concrete settings and a result preview.

Supported inputs: CSV, TSV, JSON, JSONL, SQLite and NOAA Global Hourly files. The browser interface reads files inside the project folder and its subfolders.

## Start

With Python installed, double-click `run_ui.bat` in the project folder. Keep its window open and visit **http://127.0.0.1:8765/**. If the server is already running, simply open the address.

## Use

1. **Select a source.** Click a listed project file or enter its path relative to the project folder, such as `examples/reader_data.json`. Leave Format on auto-detect unless an explicit reader is needed. For SQLite, enter the table name. For JSON records inside an object, enter the records key.
2. **Set optional details.** Enter provider, documentation or instrument information if known. A positive Sampling limit restricts inspection to part of the dataset; blank means a full scan. Documentation URLs are stored as metadata, not automatically researched.
3. **Describe the desired outcome.** For example, “Create a daily summary of valid observations” or “Export all records unchanged.” Leave this blank to inspect the data without requesting a plan.
4. **Click Inspect Source.** Review the source summary, field classifications, proposed units and unresolved questions. Click a field row to see its supporting evidence. Proposed meanings and confidence scores are suggestions, not proof of correctness.
5. **Correct and review.** If a unit interpretation is wrong, expand “Correct unit interpretations,” enter the replacement unit and supporting evidence, then click “Apply corrections and review again.” This changes the interpretation, not the stored values. Choose Approve, Reject or Request changes for each question and for the overall contract. Enter your name and supporting answers, then submit. Approval requires all questions to be explicitly approved and no blocking conditions.
6. **Review the workflow separately.** An approved contract may produce a plan for reading, quality filtering, aggregation or export. Confirm each processing decision, including applicable quality rules, aggregation method, period and weighting. Submit Step Decisions to update the plan. Time-based operations require an identified temporal coordinate.

## Status meanings

### Execute and save

After the plan is reviewed, use **Execute workflow**:

1. Choose the QC field and accepted codes as a JSON array, such as `["GOOD"]`, if filtering is planned.
2. For aggregation, choose a measurement, grouping fields (for example `["site"]`, or `[]` for all records), mean/sum/min/max, equal weighting, and whether missing measurements should reject the run or be dropped and counted. For time-based aggregation, choose a timestamp field and hourly/daily/monthly UTC period. Timestamps must contain an explicit timezone offset.
3. Click **Calculate preview**. Check the exact settings, row counts and first output records. This calculates in memory without saving files.
4. Enter your name, check the approval box, then click **Execute and save results**. Open the result and provenance links. Each run creates a unique `workflow_runs/<run-id>/` folder containing `result.json` and `provenance.json`.

Execution requires a full, unsampled review. Previews expire after ten minutes and can be saved once. If the source changes after review or preview, start a new inspection. Existing source files and run outputs are not overwritten.

- **Draft:** an interpretation has been prepared but not approved.
- **Needs review:** questions or requested changes remain.
- **Blocked:** a required condition or processing decision is unresolved.
- **Approved contract:** the data interpretation has been explicitly accepted; processing decisions may still be pending.
- **Reviewed plan:** the proposed processing steps have their required confirmations.

## Limits

Execution supports reading, explicit QC filtering, equal-weight mean/sum/min/max aggregation, and JSON export. It does not run arbitrary generated code, perform calibration, convert units, or modify the source dataset. Limits are 20 MiB per source and 100,000 records per execution. Use a closed SQLite snapshot without a journal/WAL. Reviews and pending previews are not restored after reload/restart; completed run files persist. A completed run is not independent scientific validation. The original demonstrator's calibration and GOOD-only publication rules remain unchanged; SUSPECT and BAD cannot be selected for publication filtering.

To stop the server, press **Ctrl+C** in its terminal window.
