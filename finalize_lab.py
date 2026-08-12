"""Finalize benchmark-dependent lab deliverables from real saved artifacts.

Run after:
    python domain_assistant.py
    python evaluate_answers.py
    python bonus_rerank.py

This script never calls an LLM and never fabricates scores. It only renders
metrics/traces already saved by the provided system-under-evaluation pipeline.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any


def load(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def short(text: str, length: int = 46) -> str:
    value = re.sub(r"\s+", " ", text).replace("|", "\\|").strip()
    return value if len(value) <= length else value[: length - 3] + "..."


def replace_section(text: str, heading: str, next_heading: str, body: str) -> str:
    start = text.index(heading)
    end = text.index(next_heading, start)
    return text[:start] + heading + "\n\n" + body.rstrip() + "\n\n" + text[end:]


def benchmark_section(results: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    lines = [
        "Generated from `artifacts/actual_answers.json` and `artifacts/benchmark_results.json`.",
        "",
        "| ID | Question (short) | Ctx Recall | Ctx Precision | Faithfulness | Relevance | Completeness | Overall | Passed? | Failure Type |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for row in results:
        lines.append(
            f"| {row['id']} | {short(row['question'])} | {fmt(row.get('context_recall'))} | "
            f"{fmt(row.get('context_precision'))} | {row['faithfulness']:.3f} | "
            f"{row['relevance']:.3f} | {row['completeness']:.3f} | {row['overall']:.3f} | "
            f"{'Yes' if row['passed'] else 'No'} | {row.get('failure_type') or '-'} |"
        )
    worst = sorted(results, key=lambda row: row["overall"])[:3]
    weakest = min(
        ("Context Recall", summary.get("avg_context_recall") or 1.0),
        ("Context Precision", summary.get("avg_context_precision") or 1.0),
        ("Faithfulness", summary["avg_faithfulness"]),
        ("Relevance", summary["avg_relevance"]),
        ("Completeness", summary["avg_completeness"]),
        key=lambda item: item[1],
    )
    lines += [
        "",
        "**Aggregate Report**",
        "",
        f"- Overall pass rate: {summary['pass_rate']:.1%}",
        f"- Avg Context Recall: {fmt(summary.get('avg_context_recall'))}",
        f"- Avg Context Precision: {fmt(summary.get('avg_context_precision'))}",
        f"- Avg Faithfulness: {summary['avg_faithfulness']:.3f}",
        f"- Avg Relevance: {summary['avg_relevance']:.3f}",
        f"- Avg Completeness: {summary['avg_completeness']:.3f}",
        f"- Failure type distribution: `{summary.get('failure_types', {})}`",
        "",
        "**Ba cases có Overall Score thấp nhất**",
        "",
    ]
    for index, row in enumerate(worst, 1):
        lines.append(
            f"{index}. ID: **{row['id']}** | Score: **{row['overall']:.3f}** | "
            f"Failure type: **{row.get('failure_type') or '-'}**"
        )
    lines += [
        "",
        "**Nhận xét ngắn**",
        "",
        f"> The weakest aggregate metric is **{weakest[0]} ({weakest[1]:.3f})**. "
        "I diagnose retrieval when Context Recall/Precision are weak, generation when retrieval is strong but Faithfulness/Completeness are weak, and a mixed failure when both sides degrade. This conclusion is based on metric combinations rather than pass rate alone.",
    ]
    return "\n".join(lines)


def rerank_section(rerank: dict[str, Any]) -> str:
    rows = rerank["results"]
    chosen = sorted(rows, key=lambda row: row["delta_precision"], reverse=True)[: max(5, min(10, len(rows)))]
    lines = [
        "Implemented `rerank_by_overlap()` and evaluated the same retrieved chunk sets. No chunk is added or removed.",
        "",
        "| ID | Recall before | Recall after | Precision before | Precision after | Delta Precision |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in chosen:
        lines.append(
            f"| {row['id']} | {row['recall_before']:.3f} | {row['recall_after']:.3f} | "
            f"{row['precision_before']:.3f} | {row['precision_after']:.3f} | {row['delta_precision']:+.3f} |"
        )
    lines += [
        "",
        f"**Average over all {len(rows)} traces:** Recall before={mean(r['recall_before'] for r in rows):.3f}, "
        f"Recall after={mean(r['recall_after'] for r in rows):.3f}, "
        f"Precision before={mean(r['precision_before'] for r in rows):.3f}, "
        f"Precision after={mean(r['precision_after'] for r in rows):.3f}.",
        "",
        "**Tại sao Recall dự kiến không đổi?**",
        "",
        "> Context Recall uses the union of tokens in the retrieved chunks. Reranking changes only order, so the union is identical. Context Precision is rank-aware, therefore moving relevant chunks earlier can improve it.",
        "",
        "**Khi nào reranking không đủ và cần sửa retriever/query/chunking?**",
        "",
        "> Reranking cannot recover evidence absent from the retrieved set. When recall is low, fix query formulation/expansion, metadata filters, chunking, top-k, or the retriever itself; use reranking mainly when evidence is present but badly ordered.",
    ]
    return "\n".join(lines)


def inspect_case(row: dict[str, Any], golden: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    pair = next(item for item in golden["qa_pairs"] if item["id"] == row["id"])
    answer = next(item for item in actual["answers"] if item["id"] == row["id"])
    gold_sources = {item["source_doc"] for item in pair["contexts"]}
    retrieved_sources = [item["source_doc"] for item in answer["retrieved_contexts"]]
    missing = sorted(gold_sources - set(retrieved_sources))
    extra = [source for source in retrieved_sources if source not in gold_sources]
    return {
        "pair": pair,
        "answer": answer,
        "gold_sources": sorted(gold_sources),
        "retrieved_sources": retrieved_sources,
        "missing": missing,
        "extra": extra,
    }


def why_chain(row: dict[str, Any], info: dict[str, Any]) -> tuple[list[str], str, str]:
    recall = row.get("context_recall")
    precision = row.get("context_precision")
    if recall is not None and recall < 0.6:
        missing = ", ".join(info["missing"]) or "some required evidence text"
        answers = [
            "The answer misses or distorts required evidence.",
            f"Retrieved context did not cover enough of the expected evidence (Context Recall={recall:.3f}).",
            f"Required source/evidence was absent or under-covered in top-k: {missing}.",
            "The lexical retriever optimizes term matching, not multi-document policy dependency or evidence coverage.",
            "There is no coverage-aware retry/query-expansion gate before generation.",
            "Root cause: retrieval coverage is insufficient for this question; add query expansion/hybrid retrieval or evidence-coverage checks before generation.",
        ]
        root = "Context is missing or irrelevant — improve retrieval"
        fix = "Add coverage-aware retrieval/query expansion and verify that required policy sources appear in top-k; monitor Context Recall first, then Completeness."
    elif precision is not None and precision < 0.6:
        answers = [
            "The answer is degraded despite relevant evidence being retrievable.",
            f"Relevant chunks are mixed with or ranked behind noise (Context Precision={precision:.3f}).",
            "BM25 ranking favors lexical overlap and can over-rank adjacent but non-decisive policy paragraphs.",
            "No second-stage reranker prioritizes chunks that cover the decision-critical facts.",
            "The generator receives a noisy context order without an evidence-priority signal.",
            "Root cause: retrieval ranking is noisy; add reranking while preserving the retrieved set.",
        ]
        root = "Context is missing or irrelevant — improve retrieval"
        fix = "Apply lexical/cross-encoder reranking and verify higher Context Precision without reducing Context Recall."
    elif row["faithfulness"] < min(row["relevance"], row["completeness"]):
        answers = [
            "The answer contains claims that are not sufficiently grounded.",
            "Retrieved evidence is better than the answer-side faithfulness score.",
            "The generator extrapolated or paraphrased beyond supported policy facts.",
            "The prompt asks for groundedness but has no claim-level verification step.",
            "Unsupported claims are not checked before returning the response.",
            "Root cause: generation grounding is not enforced after drafting.",
        ]
        root = "Context is missing or irrelevant — improve retrieval"
        fix = "Add claim-to-context grounding validation and regenerate/reject unsupported claims; verify Faithfulness."
    elif row["completeness"] <= row["relevance"]:
        answers = [
            "The answer omits required conditions, dates, amounts, or exceptions.",
            "The generator did not cover all elements present in the expected answer.",
            "Multi-part policy questions require explicit coverage of several evidence items.",
            "The current prompt does not include a structured checklist for every requested sub-question.",
            "There is no completeness check before response finalization.",
            "Root cause: generation lacks a required-fact coverage/checklist step.",
        ]
        root = "Answer is missing key information — increase context window or improve generation"
        fix = "Use a question decomposition/required-fact checklist and verify Completeness after generation."
    else:
        answers = [
            "The response does not address the user intent directly enough.",
            "Question terms/intent are weakly represented in the answer.",
            "The generator prioritized contextual detail over the requested decision/action.",
            "The prompt lacks an explicit direct-answer-first constraint for this intent.",
            "No relevance check reroutes or rewrites a low-relevance draft.",
            "Root cause: answer planning is not sufficiently intent-aware.",
        ]
        root = "Answer does not address the question — improve prompt clarity"
        fix = "Add intent-aware/direct-answer planning and rewrite low-relevance drafts; verify Relevance."
    return answers, root, fix


def reflection_text(benchmark: dict[str, Any], golden: dict[str, Any], actual: dict[str, Any]) -> str:
    results = benchmark["results"]
    summary = benchmark["summary"]
    metric_map = {
        "Context Recall": [r["context_recall"] for r in results if r.get("context_recall") is not None],
        "Context Precision": [r["context_precision"] for r in results if r.get("context_precision") is not None],
        "Faithfulness": [r["faithfulness"] for r in results],
        "Relevance": [r["relevance"] for r in results],
        "Completeness": [r["completeness"] for r in results],
        "Overall Score": [r["overall"] for r in results],
    }
    lines = [
        "# Day 14 — Reflection",
        "",
        "## Evaluation Report & Failure Analysis",
        "",
        "This report is generated from the real benchmark and retrieved-context traces.",
        "",
        "## 1. Benchmark Results Summary",
        "",
        f"**Overall pass rate:** {summary['pass_rate']:.1%}",
        "",
        "| Metric | Average | Min | Max | Nhận xét |",
        "|---|---:|---:|---:|---|",
    ]
    for name, values in metric_map.items():
        avg = mean(values) if values else 0.0
        note = "Good" if avg >= 0.8 else "Needs Work" if avg >= 0.6 else "Significant Issues"
        lines.append(f"| {name} | {avg:.3f} | {min(values):.3f} | {max(values):.3f} | {note} |")

    counts = Counter((r.get("failure_type") or "passed") for r in results)
    failed_count = sum(v for k, v in counts.items() if k != "passed")
    lines += [
        "",
        "**Failure type distribution**",
        "",
        "| Failure Type | Count | Percentage of all cases |",
        "|---|---:|---:|",
    ]
    for failure_type in ["hallucination", "irrelevant", "incomplete", "off_topic", "refusal"]:
        count = counts.get(failure_type, 0)
        lines.append(f"| {failure_type} | {count} | {count / len(results):.1%} |")

    ar = summary.get("avg_context_recall") or 0.0
    ap = summary.get("avg_context_precision") or 0.0
    af = summary["avg_faithfulness"]
    ac = summary["avg_completeness"]
    if ar < 0.7:
        diagnosis = f"Retrieval is the primary bottleneck: average Context Recall is {ar:.3f}; missing evidence can also depress Completeness ({ac:.3f})."
    elif ap < 0.7:
        diagnosis = f"Retrieval ranking/noise is the main issue: recall is {ar:.3f} but precision is only {ap:.3f}."
    elif af < 0.7:
        diagnosis = f"Generation grounding is the main issue: retrieval is relatively healthy but Faithfulness is {af:.3f}."
    else:
        diagnosis = f"The system is mixed/mostly healthy: Recall={ar:.3f}, Precision={ap:.3f}, Faithfulness={af:.3f}; remaining failures should be handled case-by-case."
    lines += ["", "**Chẩn đoán tổng quan**", "", f"> {diagnosis}", "", "---", "", "## 2. Top 3 Worst Failures — 5 Whys", ""]

    worst = sorted(results, key=lambda r: r["overall"])[:3]
    cluster_ids: defaultdict[str, list[str]] = defaultdict(list)
    for index, row in enumerate(worst, 1):
        info = inspect_case(row, golden, actual)
        chain, root, fix = why_chain(row, info)
        cluster = "retrieval" if (row.get("context_recall") or 1) < 0.6 or (row.get("context_precision") or 1) < 0.6 else (row.get("failure_type") or "generation")
        cluster_ids[cluster].append(row["id"])
        pair, answer = info["pair"], info["answer"]
        evidence = (
            f"Gold sources={info['gold_sources']}; retrieved sources={info['retrieved_sources']}. "
            f"Missing gold sources={info['missing'] or 'none'}; extra/noise sources={info['extra'] or 'none'}."
        )
        lines += [
            f"### Failure {index}: {row['id']}", "",
            f"**Question:** {pair['question']}", "",
            f"**Expected answer:** {pair['expected_answer']}", "",
            f"**Actual answer:** {answer['actual_answer']}", "",
            f"**Scores:** Context Recall={fmt(row.get('context_recall'))} | Context Precision={fmt(row.get('context_precision'))} | Faithfulness={row['faithfulness']:.3f} | Relevance={row['relevance']:.3f} | Completeness={row['completeness']:.3f} | Overall={row['overall']:.3f}", "",
            f"**Evidence inspection:** {evidence}", "",
            "| Level | Question | Answer |", "|---|---|---|",
            f"| Symptom | Vấn đề quan sát được là gì? | {chain[0]} |",
            f"| Why 1 | Tại sao symptom xảy ra? | {chain[1]} |",
            f"| Why 2 | Tại sao nguyên nhân trên xảy ra? | {chain[2]} |",
            f"| Why 3 | Tại sao vấn đề đó chưa được ngăn chặn? | {chain[3]} |",
            f"| Why 4 | Tại sao cơ chế hiện tại chưa phát hiện hoặc xử lý được? | {chain[4]} |",
            f"| Why 5 | Root cause có thể hành động được là gì? | {chain[5]} |",
            "", f"**Root cause:** {root}", "", f"**Proposed fix:** {fix}", "",
        ]

    lines += ["---", "", "## 3. Failure Clustering", "", "| Cluster | Root Cause | Failure IDs | Priority |", "|---|---|---|---|"]
    priority = 1
    for cluster, ids in sorted(cluster_ids.items(), key=lambda item: -len(item[1])):
        cause = "Retrieval coverage/ranking" if cluster == "retrieval" else f"{cluster} generation behavior"
        lines.append(f"| {priority} | {cause} | {', '.join(ids)} | {'High' if priority == 1 else 'Medium'} |")
        priority += 1
    lines += [
        "", "**Nếu chỉ được sửa một cluster:**", "",
        "> I would fix the highest-frequency/highest-risk cluster first, because one systemic change can improve multiple golden cases and can be verified with aggregate + per-case regression metrics rather than patching individual answers.",
        "", "---", "", "## 4. Improvement Log", "",
        benchmark.get("failure_analysis", {}).get("improvement_log", "No failing rows were logged."),
        "", "**Ba improvement suggestions ưu tiên**", "",
    ]
    suggestions = benchmark.get("failure_analysis", {}).get("suggestions", [])[:3]
    while len(suggestions) < 3:
        suggestions.append("Add the lowest-scoring case to the regression benchmark and verify it after each retrieval/prompt change")
    for index, suggestion in enumerate(suggestions, 1):
        lines.append(f"{index}. {suggestion}")
    lines += [
        "", "| Suggestion | Target metric | Verification method |", "|---|---|---|",
        f"| {suggestions[0]} | Faithfulness / Context Recall | Re-run the same 20-case benchmark and compare aggregate + worst-case scores. |",
        f"| {suggestions[1]} | Relevance / Completeness | Require no >0.05 regression and inspect the previous worst cases. |",
        f"| {suggestions[2]} | Context Precision / failure count | Run reranking and verify recall is unchanged while precision/failure rate improves. |",
        "", "---", "", "## 5. Regression Testing Strategy", "",
        "**Câu 1:** Run `run_regression()` on every code/prompt/retrieval/corpus change, before release, and after a failure-driven fix. Keep the previous accepted release as the baseline.", "",
        "**Câu 2:** A 0.05 aggregate drop is a useful lab default, but Student Services should also use hard per-case gates for safety/privacy, wrong deadlines/amounts, and adversarial failures because a small average drop can hide one severe policy error.", "",
        "**Câu 3:** Block deployment on Faithfulness regression, privacy/safety failure, fabricated policy, or material wrong deadline/amount. Alert (then review) on modest Context Precision/verbosity/latency degradation when required evidence and correctness remain intact.", "",
        "**Flow:** `Code/prompt/retrieval change → Offline golden benchmark → Regression + adversarial gates → Human review of failures → Deploy`", "",
        "---", "", "## 6. Continuous Improvement Loop", "",
        "`Evaluate → Analyze → Improve → Augment benchmark → Repeat`", "",
        "| Priority | Action | Metric dự kiến cải thiện | Expected impact |", "|---:|---|---|---|",
        "| 1 | Fix the dominant root-cause cluster from the worst cases | Context Recall/Precision or Faithfulness | Improves several failures with one systemic change |",
        "| 2 | Add reranking/coverage checks where evidence is present but noisy | Context Precision | Puts decisive policy evidence earlier without changing recall |",
        "| 3 | Add previous failures as permanent regression cases | Failure recurrence rate | Prevents the same failure from returning after later changes |",
        "", "**Cases to add next:** paraphrased versions of the three current lowest-scoring questions plus one adversarial variant that preserves the same policy intent while changing surface wording.", "",
        "---", "", "## 7. Final Reflection", "",
        "**Điều gì trái với dự đoán ban đầu?**", "",
        "> A single pass rate is much less informative than the metric pattern and retrieved trace. A response can be grounded but incomplete, or retrieval can contain the needed source yet rank it behind noise. The failure analysis therefore has to separate retrieval-side and answer-side evidence.", "",
        "**Giới hạn của word-overlap heuristics và production metrics:**", "",
        "> Token overlap misses semantic equivalence, negation, numerical/policy logic, and whether a claim is entailed rather than merely sharing words. In production I would keep deterministic regression checks but add semantic/claim-level groundedness, LLM-as-a-Judge calibrated to human labels, citation/evidence entailment, safety/privacy tests, latency/cost, and online user-feedback metrics. High-risk policy cases should still receive human calibration/review.", "",
        f"Failed cases in this run: **{failed_count}/{len(results)}**.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    benchmark = load("artifacts/benchmark_results.json")
    golden = load("golden_dataset.json")
    actual = load("artifacts/actual_answers.json")
    rerank = load("artifacts/bonus_rerank_results.json")

    exercises_path = Path("exercises.md")
    exercises = exercises_path.read_text(encoding="utf-8")
    exercises = replace_section(
        exercises,
        "### Exercise 3.2 — Benchmark Run",
        "### Exercise 3.3 — LLM-as-a-Judge Rubric Design",
        benchmark_section(benchmark["results"], benchmark["summary"]),
    )
    exercises = replace_section(
        exercises,
        "### Exercise 3.5 — Retrieval Reranking (Bonus +5)",
        "---\n\n## Completion Checklist",
        rerank_section(rerank),
    )
    exercises = exercises.replace(
        "- [ ] Exercise 3.2 numeric table is generated from the real OpenAI run artifact.",
        "- [x] Exercise 3.2 numeric table is generated from the real OpenAI run artifact.",
    ).replace(
        "- [ ] `reflection.md` numeric/trace-specific fields are finalized after the same real benchmark run.",
        "- [x] `reflection.md` numeric/trace-specific fields are finalized after the same real benchmark run.",
    )
    exercises_path.write_text(exercises, encoding="utf-8")
    Path("reflection.md").write_text(reflection_text(benchmark, golden, actual), encoding="utf-8")
    print("Finalized exercises.md and reflection.md from real benchmark artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
