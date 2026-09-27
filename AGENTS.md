# Scientific safety rules for AI-assisted changes

This repository demonstrates safe modernization of scientific database pipelines.

Before changing SQL, calibration logic, QC filtering, units, aggregation, or output schemas:

1. Read `scientific_contract.yaml`.
2. Identify affected variables, transformations, assumptions, quality rules, and tolerances.
3. Use `docs/dependency_graph.json` to trace downstream scientific products.
4. State the expected scientific impact before editing.
5. Run `python scripts/validate.py` and `python -m unittest discover -s tests -v` after editing.
6. Reject or revert a change if reference results exceed the contract tolerance.
7. Record any intentional scientific change in the contract, reference dataset, and provenance docs.

Never weaken a validation tolerance merely to make a failing implementation pass. Never include `SUSPECT` or `BAD` observations in published products unless the Scientific Contract and reference dataset are deliberately revised and reviewed.

