# Hackathon demo runbook

Target length: about 2 minutes 30 seconds, leaving room inside the three-minute submission limit.

## 1. Problem — 20 seconds

Show the valid-looking SQL in the controlled pipeline. Explain that ordinary tests can verify execution and shape while missing a scientifically wrong constant.

## 2. Contract — 25 seconds

Open `scientific_contract.yaml`. Highlight variable semantics, units, T002's equation, QC policy, code mapping, and numerical tolerance.

## 3. Detect — 35 seconds

Run:

```powershell
python scripts/validate.py --pipeline scenarios/controlled_failure/database_pipeline.py
```

Show the failed constant check and three regression rows, each biased by 0.15 K. Point to the reported transformations and affected outputs.

## 4. Trace and repair with Bob — 45 seconds

Ask Bob to use the `controlled-regression-repair` skill. Show Bob reading the contract, locating T002 and `KELVIN_OFFSET`, preserving the QC/calibration logic, and correcting the implementation without touching reference data or tolerance.

## 5. Prove — 30 seconds

Run:

```powershell
python scripts/run_demo.py
python -m unittest discover -s tests -v
```

Show 23/27 before, 27/27 after, zero remaining violations, and 10 passing repository tests.

## 6. Close — 15 seconds

State the proposition: Bob supplies the engineering loop; the Scientific Contract supplies the domain truth. Safe modernization means the scientific result remains valid and traceable—not merely that the software still runs.

