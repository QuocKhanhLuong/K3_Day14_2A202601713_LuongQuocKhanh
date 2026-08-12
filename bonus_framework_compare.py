"""Exercise 3.4 bonus: compare the lab RAGAS-style evaluator with DeepEval.

The comparison uses the exact same 20 questions, actual answers, expected
answers, and retrieved-context traces. It writes a machine-readable artifact
and replaces only the Exercise 3.4 section in exercises.md with measured
results.

Run after:
    python domain_assistant.py
    python evaluate_answers.py
"""
from __future__ import annotations

import json
import math
import os
from importlib.metadata import version
from pathlib import Path
from statistics import mean
from typing import Any

from dotenv import load_dotenv

GOLDEN_PATH = Path("golden_dataset.json")
ACTUAL_PATH = Path("artifacts/actual_answers.json")
BENCHMARK_PATH = Path("artifacts/benchmark_results.json")
OUTPUT_PATH = Path("artifacts/bonus_framework_comparison.json")
EXERCISES_PATH = Path("exercises.md")

SECTION_HEADING = "### Exercise 3.4 — Framework Comparison (Bonus +10)"
NEXT_HEADING = "### Exercise 3.5 — Retrieval Reranking (Bonus +5)"


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. Run domain_assistant.py and evaluate_answers.py first."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    mx, my = mean(xs), mean(ys)
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    denominator = math.sqrt(sum(x * x for x in dx) * sum(y * y for y in dy))
    if denominator == 0:
        return None
    return sum(x * y for x, y in zip(dx, dy)) / denominator


def _replace_section(text: str, body: str) -> str:
    start = text.index(SECTION_HEADING)
    end = text.index(NEXT_HEADING, start)
    return text[:start] + SECTION_HEADING + "\n\n" + body.rstrip() + "\n\n" + text[end:]


def _metric_bundle(model: str):
    from deepeval.metrics import (
        AnswerRelevancyMetric,
        ContextualPrecisionMetric,
        ContextualRecallMetric,
        FaithfulnessMetric,
        GEval,
    )
    from deepeval.test_case import SingleTurnParams

    common = {
        "threshold": None,
        "model": model,
        "include_reason": True,
        "async_mode": False,
    }
    return {
        "faithfulness": FaithfulnessMetric(**common),
        "relevance": AnswerRelevancyMetric(**common),
        "context_recall": ContextualRecallMetric(**common),
        "context_precision": ContextualPrecisionMetric(**common),
        "completeness": GEval(
            name="Completeness",
            criteria=(
                "Assess whether the actual output covers all material facts, "
                "conditions, dates, amounts, exceptions, and required actions "
                "contained in the expected output. Do not reward verbosity and "
                "penalize omission of decision-critical details."
            ),
            evaluation_params=[
                SingleTurnParams.INPUT,
                SingleTurnParams.ACTUAL_OUTPUT,
                SingleTurnParams.EXPECTED_OUTPUT,
            ],
            threshold=None,
            model=model,
            async_mode=False,
        ),
    }


def _measure(metric: Any, test_case: Any) -> dict[str, Any]:
    metric.measure(test_case)
    score = getattr(metric, "score", None)
    if score is None:
        raise RuntimeError(f"{metric.__class__.__name__} returned no score")
    return {"score": float(score), "reason": getattr(metric, "reason", None)}


def _render_section(rows: list[dict[str, Any]], summary: dict[str, Any], model: str, deepeval_version: str) -> str:
    labels = {
        "context_recall": "Context Recall",
        "context_precision": "Context Precision",
        "faithfulness": "Faithfulness",
        "relevance": "Relevance / Answer Relevancy",
        "completeness": "Completeness",
    }
    lines = [
        "**Method.** I compared the lab's deterministic **RAGAS-style evaluator** against **DeepEval** on the exact same 20 records. For every ID, both frameworks receive the same question, generated answer, expected answer, and retrieved chunk list; no answer is regenerated for this comparison.",
        "",
        f"- DeepEval version: `{deepeval_version}`",
        f"- DeepEval judge model: `{model}`",
        "- Lab evaluator: token-overlap Faithfulness/Relevance/Completeness plus Context Recall and rank-aware Context Precision.",
        "- DeepEval: `FaithfulnessMetric`, `AnswerRelevancyMetric`, `ContextualRecallMetric`, `ContextualPrecisionMetric`, plus a domain-specific `GEval` completeness metric.",
        "",
        "| Aligned metric | Lab RAGAS-style avg | DeepEval avg | Pearson r across 20 cases |",
        "|---|---:|---:|---:|",
    ]
    for key in ["context_recall", "context_precision", "faithfulness", "relevance", "completeness"]:
        item = summary["metrics"][key]
        corr = item["pearson_r"]
        corr_text = "n/a" if corr is None else f"{corr:.3f}"
        lines.append(f"| {labels[key]} | {item['lab_avg']:.3f} | {item['deepeval_avg']:.3f} | {corr_text} |")

    disagreement = sorted(rows, key=lambda row: row["mean_absolute_metric_gap"], reverse=True)[:5]
    lines += [
        "",
        "**Five cases with the largest cross-framework disagreement**",
        "",
        "| ID | Mean absolute metric gap | Lab Overall | DeepEval mean |",
        "|---|---:|---:|---:|",
    ]
    for row in disagreement:
        lines.append(f"| {row['id']} | {row['mean_absolute_metric_gap']:.3f} | {row['lab']['overall']:.3f} | {row['deepeval_mean']:.3f} |")

    lines += [
        "",
        "**Result / interpretation.**",
        "",
        "> The raw scores are not expected to match exactly: the lab evaluator is deterministic lexical overlap, while DeepEval uses LLM-as-a-judge semantics. The useful comparison is whether both methods expose similar weak cases and whether aligned metrics move in the same direction. Large disagreement cases are especially valuable for manual review because they reveal where lexical coverage and semantic judgment disagree.",
        "",
        f"Machine-readable evidence: `{OUTPUT_PATH}`.",
    ]
    return "\n".join(lines)


def main() -> int:
    load_dotenv(Path(__file__).resolve().with_name(".env"))
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is missing. Put it in .env or export it before running.")

    model = os.getenv("DEEPEVAL_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
    golden = _load(GOLDEN_PATH)
    actual = _load(ACTUAL_PATH)
    benchmark = _load(BENCHMARK_PATH)

    golden_rows = golden["qa_pairs"]
    actual_by_id = {row["id"]: row for row in actual["answers"]}
    benchmark_by_id = {row["id"]: row for row in benchmark["results"]}
    if len(golden_rows) != 20:
        raise ValueError(f"Expected 20 golden records, found {len(golden_rows)}")

    from deepeval.test_case import LLMTestCase

    metrics = _metric_bundle(model)
    rows: list[dict[str, Any]] = []
    deepeval_version = version("deepeval")
    print(f"Running DeepEval {deepeval_version} on {len(golden_rows)} cases with judge model {model}...")

    for index, pair in enumerate(golden_rows, 1):
        case_id = pair["id"]
        actual_row = actual_by_id[case_id]
        benchmark_row = benchmark_by_id[case_id]
        if actual_row.get("error"):
            raise RuntimeError(f"{case_id} has generation error: {actual_row['error']}")

        retrieved_context = [chunk["text"] for chunk in actual_row["retrieved_contexts"]]
        test_case = LLMTestCase(
            input=pair["question"],
            actual_output=actual_row["actual_answer"],
            expected_output=pair["expected_answer"],
            context=[ctx["evidence"] for ctx in pair["contexts"]],
            retrieval_context=retrieved_context,
        )

        print(f"[{index:02d}/20] {case_id}")
        deepeval_scores = {key: _measure(metric, test_case) for key, metric in metrics.items()}
        lab_scores = {
            "context_recall": float(benchmark_row["context_recall"]),
            "context_precision": float(benchmark_row["context_precision"]),
            "faithfulness": float(benchmark_row["faithfulness"]),
            "relevance": float(benchmark_row["relevance"]),
            "completeness": float(benchmark_row["completeness"]),
            "overall": float(benchmark_row["overall"]),
        }
        aligned_keys = ["context_recall", "context_precision", "faithfulness", "relevance", "completeness"]
        gaps = [abs(lab_scores[key] - deepeval_scores[key]["score"]) for key in aligned_keys]
        rows.append({
            "id": case_id,
            "lab": lab_scores,
            "deepeval": deepeval_scores,
            "deepeval_mean": mean(deepeval_scores[key]["score"] for key in aligned_keys),
            "mean_absolute_metric_gap": mean(gaps),
        })

    metric_summary: dict[str, Any] = {}
    for key in ["context_recall", "context_precision", "faithfulness", "relevance", "completeness"]:
        lab_values = [row["lab"][key] for row in rows]
        deepeval_values = [row["deepeval"][key]["score"] for row in rows]
        metric_summary[key] = {
            "lab_avg": mean(lab_values),
            "deepeval_avg": mean(deepeval_values),
            "pearson_r": _pearson(lab_values, deepeval_values),
        }

    summary = {
        "case_count": len(rows),
        "metrics": metric_summary,
        "avg_mean_absolute_metric_gap": mean(row["mean_absolute_metric_gap"] for row in rows),
    }
    payload = {
        "comparison": "lab_ragas_style_vs_deepeval",
        "same_inputs": True,
        "deepeval_version": deepeval_version,
        "judge_model": model,
        "summary": summary,
        "results": rows,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    exercises = EXERCISES_PATH.read_text(encoding="utf-8")
    section = _render_section(rows, summary, model, deepeval_version)
    EXERCISES_PATH.write_text(_replace_section(exercises, section), encoding="utf-8")

    print(f"Saved: {OUTPUT_PATH}")
    print(f"Updated: {EXERCISES_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
