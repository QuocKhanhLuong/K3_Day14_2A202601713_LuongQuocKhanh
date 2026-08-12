"""Exercise 3.5: measure retrieval metrics before/after lexical reranking.

Requires artifacts/actual_answers.json produced by domain_assistant.py.
The retrieved set is preserved; only chunk order changes.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from template import RAGASEvaluator, rerank_by_overlap


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    golden = _load(Path("golden_dataset.json"))
    actual = _load(Path("artifacts/actual_answers.json"))
    actual_by_id = {item["id"]: item for item in actual["answers"]}
    evaluator = RAGASEvaluator()
    rows: list[dict[str, Any]] = []

    for pair in golden["qa_pairs"]:
        item = actual_by_id[pair["id"]]
        chunks = [chunk["text"] for chunk in item["retrieved_contexts"]]
        reranked = rerank_by_overlap(chunks, pair["expected_answer"])
        recall_before = evaluator.evaluate_context_recall(chunks, pair["expected_answer"])
        recall_after = evaluator.evaluate_context_recall(reranked, pair["expected_answer"])
        precision_before = evaluator.evaluate_context_precision(chunks, pair["expected_answer"])
        precision_after = evaluator.evaluate_context_precision(reranked, pair["expected_answer"])
        rows.append({
            "id": pair["id"],
            "recall_before": recall_before,
            "recall_after": recall_after,
            "precision_before": precision_before,
            "precision_after": precision_after,
            "delta_precision": precision_after - precision_before,
            "same_chunk_set": sorted(chunks) == sorted(reranked),
        })

    output = {"method": "rerank_by_overlap", "results": rows}
    out = Path("artifacts/bonus_rerank_results.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")

    print("| ID | Recall before | Recall after | Precision before | Precision after | Delta Precision |")
    print("|---|---:|---:|---:|---:|---:|")
    for row in rows:
        print(
            f"| {row['id']} | {row['recall_before']:.3f} | {row['recall_after']:.3f} | "
            f"{row['precision_before']:.3f} | {row['precision_after']:.3f} | {row['delta_precision']:+.3f} |"
        )
    assert all(row["same_chunk_set"] for row in rows)
    assert all(abs(row["recall_before"] - row["recall_after"]) < 1e-12 for row in rows)
    print(f"\nSaved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
