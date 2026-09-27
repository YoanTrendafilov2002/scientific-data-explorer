from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.contract import load_contract  # noqa: E402


def node_id(value: str) -> str:
    return "n_" + "".join(character if character.isalnum() else "_" for character in value)


def main() -> int:
    contract = load_contract(ROOT / "scientific_contract.yaml")
    nodes: dict[str, dict[str, str]] = {}
    edges: list[dict[str, str]] = []
    mermaid = ["flowchart LR"]

    for variable in contract["variables"]:
        identifier = variable["id"]
        nodes[identifier] = {"id": identifier, "kind": "variable", "classification": variable["classification"]}
        mermaid.append(f'  {node_id(identifier)}["{identifier}\\n{variable["classification"]}"]')

    for transformation in contract["transformations"]:
        identifier = transformation["id"]
        nodes[identifier] = {"id": identifier, "kind": "transformation", "label": transformation["name"]}
        mermaid.append(f'  {node_id(identifier)}{{"{identifier}: {transformation["name"]}"}}')
        for input_variable in transformation["inputs"]:
            edges.append({"from": input_variable, "to": identifier, "relation": "input_to"})
            mermaid.append(f"  {node_id(input_variable)} --> {node_id(identifier)}")
        for output_variable in transformation["outputs"]:
            edges.append({"from": identifier, "to": output_variable, "relation": "produces"})
            mermaid.append(f"  {node_id(identifier)} --> {node_id(output_variable)}")

    for mapping in contract["code_mappings"]:
        code_id = f'{mapping["file"]}::{mapping["symbol"]}'
        nodes[code_id] = {"id": code_id, "kind": "code", "label": mapping["symbol"]}
        edges.append({"from": code_id, "to": mapping["transformation"], "relation": "implements"})
        mermaid.append(f'  {node_id(code_id)}[["{mapping["symbol"]}"]] -. implements .-> {node_id(mapping["transformation"])}')

    output = {"nodes": list(nodes.values()), "edges": edges}
    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "dependency_graph.json").write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    (docs / "dependency_graph.mmd").write_text("\n".join(mermaid) + "\n", encoding="utf-8")
    print(f"Generated {len(nodes)} nodes and {len(edges)} edges.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
