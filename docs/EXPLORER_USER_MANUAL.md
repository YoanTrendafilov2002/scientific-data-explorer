# Scientific Data Explorer — User Manual

## What the program does

The program has two interfaces:

- **Explorer:** open a local dataset, select columns, draw common graphs and inspect source rows. This is an exploratory view, not a scientific approval.
- **Reviewed workflow:** inspect the source, review proposed meanings and units, approve supported processing steps, calculate a preview, and separately approve saving results with provenance.

It supports several local file formats through a shared reader. It does not connect to every database or infer scientifically correct interpretations automatically.

## Quick links

- [Open the currently running Explorer](http://127.0.0.1:8766/explorer).
- [Open the currently running reviewed workflow](http://127.0.0.1:8766/).
- [Detailed workflow instructions](USER_MANUAL.md).
- [Three-minute presentation script](PRESENTATION_3_MIN.md).
- [Palmer Penguins CSV — save this file to try the Explorer](https://raw.githubusercontent.com/allisonhorst/palmerpenguins/main/inst/extdata/penguins.csv).
- [Palmer Penguins documentation and attribution](https://allisonhorst.github.io/palmerpenguins/).
- [UCI Iris documentation, download and units](https://archive.ics.uci.edu/dataset/53/iris).

The localhost links work only on the computer running the current server. They are not public website links. The launcher normally chooses a free port, which may differ from 8766; use the address it opens or prints. Documentation links within this package remain usable after extraction in a Markdown viewer.

## 1. Start and stop

1. Extract the ZIP before launching it.
2. Install Python 3.10 or newer if it is not already available. No additional Python packages are required.
3. On Windows, double-click **Start Explorer.bat** in the extracted folder.
4. A browser opens the Explorer. Keep the accompanying terminal window open.
5. Stop the app with **Ctrl+C** in that terminal.

On macOS/Linux, open a terminal in the extracted folder and run:

```sh
python3 scripts/launch_explorer.py
```

The app runs on loopback only. Do not expose it through a public tunnel or use it as a multi-user production service. The portable package contains source code; it is not a standalone executable.

## 2. Choose a dataset

Use one of the following, then click **Load data**:

| Control | How to use it |
|---|---|
| Project dataset | Select an existing example from the dropdown. |
| Or project-relative path | Enter a path inside the extracted project, such as `examples/reader_data.json`. This is a file path, not a URL. |
| Or browse your computer | Choose a supported file anywhere on your computer. It is copied to a temporary local file for reading, then that copy is removed. Your original is unchanged. |

The Explorer does not fetch a dataset from a web URL. Download it first, then use **Browse**.

### Supported inputs

- **CSV/TSV:** the first row must contain unique, nonempty column names. CSV uses commas and TSV uses tabs. Use a UTF-8 export.
- **JSON:** an array of row objects, or an object containing that array. For `{"records": [...]}`, enter `records` in **JSON array key**. This is a top-level key, not a nested JSONPath expression.
- **JSONL/NDJSON:** one row object per line, without blank lines.
- **SQLite (`.db`, `.sqlite`, `.sqlite3`):** use a closed, self-contained snapshot. Load once to list tables; choose a **SQLite table** and click **Load data** again. SQL queries and joins cannot be entered here.

Excel workbooks, ZIP/HTML dashboards and remote database connections are not supported by this picker. Nested objects are shown in the table, but their inner fields are not automatically available as plot axes. The specialized NOAA adapter is available through the reviewed workflow, not as a decoding option in the simple Explorer.

## 3. Choose columns and a graph

After loading, the graph updates when you change **Graph**, **X / row label**, or **Y / measurement**.

| Graph | Select | What it means |
|---|---|---|
| Scatter plot | Numeric X and Y; or Row number for X | One point per valid row. Use it to inspect the relationship between two measurements. Overlapping points can hide multiple observations. |
| Line plot (row order) | Numeric Y | Values connected in the file's row order, with gaps where Y is invalid. It does not sort timestamps or create a calibrated time series. X selection supplies point labels, not horizontal coordinates. |
| Bar chart (individual rows) | Row-label field and numeric Y | One bar per valid row, maximum 40 loaded rows. Duplicate labels are not combined. Bars include zero in the scale. |
| Histogram (10 bins) | Numeric Y; X is disabled | Counts of numeric values in equal-width bins. Constant values produce one bin. The last bin includes the maximum. Hover or focus a bar for its bounds. |

Hover over or keyboard-focus marks to inspect values. Use the data table for original cells. Numeric-looking identifiers may appear in the selectors; selecting them does not make them scientific measurements.

### Missing values and units

Empty values, nulls, booleans, nested objects and non-numeric text are not plotted as numbers. Omitted rows are counted below the chart. For example, the text `NA` is omitted from a numeric graph but remains `NA` in the table; zero remains zero.

Units are not inferred or converted. Read source documentation before comparing fields. The Explorer applies no calibration, imputation, QC filtering or scientific approval. BAD and SUSPECT rows can appear in raw exploration; they are not thereby approved for publication. Ordinary binary floating-point precision applies to plotted numbers.

## 4. A working example: Palmer Penguins

The [official package documentation](https://allisonhorst.github.io/palmerpenguins/) describes 344 penguins and provides attribution and CC0 licensing information. Download the [CSV](https://raw.githubusercontent.com/allisonhorst/palmerpenguins/main/inst/extdata/penguins.csv), saving it as `penguins.csv` rather than an HTML page.

1. Browse for `penguins.csv` and click **Load data**. Leave SQLite table and JSON array key blank.
2. Choose **Scatter plot**.
3. Set X to `flipper_length_mm` and Y to `body_mass_g`.
4. In the snapshot tested during this project, 344 rows load; 342 have numeric values for both selected fields and two are omitted. If a future download differs, trust the loaded counts rather than this historical number.
5. Switch to **Histogram**, keeping Y as `body_mass_g`. Inspect the bin bounds and counts.
6. Look at the table to see that missing values were not filled in.

No biological conclusion or causal relationship is established by this demonstration.

For an offline check, use the included `examples/reader_data.json`: select Y `temperature`, X **Row number**, and a line or bar chart. It has three synthetic rows, two numeric temperatures and one null. One numeric row is labeled SUSPECT, deliberately illustrating why raw exploration and approved processing are different.

## 5. Run a reviewed workflow

Click **Open reviewed workflow**. An Explorer upload is temporary and is not automatically transferred to this interface. To process that file, place a copy inside the project and enter its project-relative path in the workflow interface.

1. Select the source and describe a supported outcome, such as an unchanged export or an equal-weight mean grouped by a field.
2. Inspect the source. Review proposed classifications, units, evidence and unresolved questions.
3. Supply documented corrections and explicit decisions. Do not approve an unknown unit or timezone simply to continue.
4. Review the proposed processing steps separately from the contract.
5. Choose exact execution settings, including any QC rules, grouping, aggregation and missing-value policy.
6. Calculate the preview, check its settings and counts, then separately approve saving it.
7. Open the returned result and provenance links. Files are saved under `workflow_runs/<run-id>/`.

See [the workflow manual](USER_MANUAL.md) for field-by-field instructions. Supported execution is bounded reading, explicit QC filtering, equal-weight mean/sum/min/max aggregation and JSON export—not arbitrary generated code, automatic calibration or unit conversion. A saved run is not independent scientific certification.

## 6. Limits and troubleshooting

| Symptom or limit | What to do |
|---|---|
| Localhost link fails | Start the launcher and use the address it prints. Closing the server stops the page's API. |
| Python is not recognized | Make Python 3.10+ available, then rerun the launcher. |
| Upload larger than 5 MiB | Put the file inside the project and enter its relative path; project sources still have a 20 MiB cap. |
| More than 5,000 rows | Explorer plots only the first 5,000 and labels the view partial. Do not interpret it as a full-population sample. |
| Table shows fewer rows than the chart | The table displays the first 100 loaded rows; charts can use up to 5,000. |
| No valid numeric values | Choose different columns; inspect missing values and nested objects in the table. |
| Bar chart refuses a dataset | It permits at most 40 loaded rows. Use scatter/histogram or a smaller, explicitly prepared result. |
| JSON asks for an array | Supply the top-level array key, or provide a row-array JSON file. Saved workflow results use `records`. |
| SQLite asks for a table | Load the database, choose a listed table, then load again. |
| WAL/journal warning | Obtain a closed self-contained SQLite snapshot. Do not delete journal files to force it through. |
| SQLite BLOB or nonfinite values | Prepare an explicit compatible projection; the Explorer does not silently rewrite these values. |
| Workflow is blocked | Resolve its actual questions and decisions. Explorer success does not approve the workflow. |
| Preview expired/source changed | Inspect and review again. Execution previews last ten minutes and are single-use. |

Reviewed execution has separate caps: 20 MiB and 100,000 records, with a full unsampled review required. Neither mode modifies original source files. The Explorer does not save graphs or scientific outputs. Its core operation uses no cloud services; opening external documentation/download links does access those websites.

## 7. Verify the installation

From the extracted project folder:

```sh
python -m unittest discover -s tests -q
python scripts/validate.py
```

Optional developer chart tests, if Node is installed:

```sh
node tests/test_explorer_charts.cjs
```

The September 27, 2026 packaged build was checked after fresh extraction: 182 Python tests and all 27 original scientific checks passed. These are software/reference checks, not proof that an arbitrary dataset is scientifically valid.
