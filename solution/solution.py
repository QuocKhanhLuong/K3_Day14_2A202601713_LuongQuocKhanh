"""Day 14 — AI Evaluation & Benchmarking Pipeline.

Completed evaluation core for the Northstar Student Services lab.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class QAPair:
    question: str
    expected_answer: str
    context: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    retrieved_contexts: list[str] = field(default_factory=list)


@dataclass
class EvalResult:
    qa_pair: QAPair
    actual_answer: str
    faithfulness: float
    relevance: float
    completeness: float
    passed: bool
    failure_type: str | None = None
    context_precision: float | None = None
    context_recall: float | None = None

    def overall_score(self) -> float:
        return (self.faithfulness + self.relevance + self.completeness) / 3.0


STOPWORDS: set[str] = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "of", "in", "on", "at", "to", "for", "with", "as", "by", "and", "or",
    "it", "its", "this", "that", "these", "those", "from", "into", "than",
}


def _tokenize(text: str | None) -> set[str]:
    if not text:
        return set()
    tokens = re.findall(r"\b\w+\b", text.lower())
    return {token for token in tokens if token not in STOPWORDS}


def _clamp(score: float) -> float:
    return max(0.0, min(1.0, float(score)))


class RAGASEvaluator:
    def evaluate_faithfulness(self, answer: str, context: str) -> float:
        answer_tokens = _tokenize(answer)
        if not answer_tokens:
            return 1.0
        context_tokens = _tokenize(context)
        return _clamp(len(answer_tokens & context_tokens) / len(answer_tokens))

    def evaluate_relevance(self, answer: str, question: str) -> float:
        question_tokens = _tokenize(question)
        if not question_tokens:
            return 1.0
        answer_tokens = _tokenize(answer)
        return _clamp(len(answer_tokens & question_tokens) / len(question_tokens))

    def evaluate_completeness(self, answer: str, expected: str) -> float:
        expected_tokens = _tokenize(expected)
        if not expected_tokens:
            return 1.0
        answer_tokens = _tokenize(answer)
        return _clamp(len(answer_tokens & expected_tokens) / len(expected_tokens))

    def evaluate_context_recall(self, contexts: list[str], expected: str) -> float:
        expected_tokens = _tokenize(expected)
        if not expected_tokens:
            return 1.0
        union_tokens: set[str] = set()
        for chunk in contexts:
            union_tokens.update(_tokenize(chunk))
        return _clamp(len(expected_tokens & union_tokens) / len(expected_tokens))

    def evaluate_context_precision(
        self,
        contexts: list[str],
        expected: str,
        relevance_threshold: float = 0.1,
    ) -> float:
        expected_tokens = _tokenize(expected)
        if not expected_tokens:
            return 1.0
        if not contexts:
            return 0.0

        relevant_flags: list[bool] = []
        for chunk in contexts:
            coverage = len(_tokenize(chunk) & expected_tokens) / len(expected_tokens)
            relevant_flags.append(coverage >= relevance_threshold)

        total_relevant = sum(relevant_flags)
        if total_relevant == 0:
            return 0.0

        relevant_so_far = 0
        precision_sum = 0.0
        for rank, relevant in enumerate(relevant_flags, start=1):
            if relevant:
                relevant_so_far += 1
                precision_sum += relevant_so_far / rank
        return _clamp(precision_sum / total_relevant)

    def run_full_eval(
        self,
        answer: str,
        question: str,
        context: str,
        expected: str,
        contexts: list[str] | None = None,
    ) -> EvalResult:
        faithfulness = self.evaluate_faithfulness(answer, context)
        relevance = self.evaluate_relevance(answer, question)
        completeness = self.evaluate_completeness(answer, expected)
        passed = all(score >= 0.5 for score in (faithfulness, relevance, completeness))

        failure_type: str | None = None
        if not passed:
            if faithfulness < 0.3:
                failure_type = "hallucination"
            elif relevance < 0.3:
                failure_type = "irrelevant"
            elif completeness < 0.3:
                failure_type = "incomplete"
            else:
                failure_type = "off_topic"

        context_recall: float | None = None
        context_precision: float | None = None
        if contexts is not None:
            context_recall = self.evaluate_context_recall(contexts, expected)
            context_precision = self.evaluate_context_precision(contexts, expected)

        return EvalResult(
            qa_pair=QAPair(
                question=question,
                expected_answer=expected,
                context=context or "",
                retrieved_contexts=list(contexts or []),
            ),
            actual_answer=answer,
            faithfulness=faithfulness,
            relevance=relevance,
            completeness=completeness,
            passed=passed,
            failure_type=failure_type,
            context_precision=context_precision,
            context_recall=context_recall,
        )


def rerank_by_overlap(contexts: list[str], query: str) -> list[str]:
    query_tokens = _tokenize(query)
    return sorted(
        contexts,
        key=lambda chunk: len(_tokenize(chunk) & query_tokens),
        reverse=True,
    )


class LLMJudge:
    def __init__(self, judge_llm_fn: Callable[[str], str]) -> None:
        self.judge_llm_fn = judge_llm_fn

    def score_response(
        self,
        question: str,
        answer: str,
        rubric: dict[str, Any],
    ) -> dict[str, Any]:
        rubric_text = "\n".join(f"- {name}: {description}" for name, description in rubric.items())
        prompt = (
            "You are an impartial evaluator. Score each rubric criterion and return JSON only.\n"
            "Use scores in [0,1] (or 1-5, which will be normalized).\n\n"
            f"Question:\n{question}\n\nAnswer:\n{answer}\n\nRubric:\n{rubric_text}\n"
        )
        raw = self.judge_llm_fn(prompt)
        parsed_scores: dict[str, Any] = {}
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict):
                candidate = payload.get("scores", payload)
                if isinstance(candidate, dict):
                    parsed_scores = candidate
        except (json.JSONDecodeError, TypeError):
            parsed_scores = {}

        scores: dict[str, float] = {}
        for criterion in rubric:
            value = parsed_scores.get(criterion, 0.5)
            try:
                score = float(value)
            except (TypeError, ValueError):
                score = 0.5
            if 1.0 < score <= 5.0:
                score /= 5.0
            scores[criterion] = _clamp(score)

        return {"scores": scores, "reasoning": raw}

    def detect_bias(self, scores_batch: list[dict[str, Any]]) -> dict[str, Any]:
        row_averages: list[float] = []
        all_scores: list[float] = []
        for item in scores_batch:
            values = item.get("scores", {}) if isinstance(item, dict) else {}
            numeric: list[float] = []
            if isinstance(values, dict):
                for value in values.values():
                    try:
                        numeric.append(float(value))
                    except (TypeError, ValueError):
                        continue
            if numeric:
                row_averages.append(sum(numeric) / len(numeric))
                all_scores.extend(numeric)

        overall = sum(all_scores) / len(all_scores) if all_scores else 0.5
        positional_bias = False
        if len(row_averages) >= 2:
            remaining_avg = sum(row_averages[1:]) / len(row_averages[1:])
            positional_bias = row_averages[0] > remaining_avg + 0.1

        return {
            "positional_bias": positional_bias,
            "leniency_bias": bool(all_scores) and overall > 0.8,
            "severity_bias": bool(all_scores) and overall < 0.3,
        }


class BenchmarkRunner:
    def run(
        self,
        qa_pairs: list[QAPair],
        agent_fn: Callable[[str], str],
        evaluator: RAGASEvaluator,
    ) -> list[EvalResult]:
        results: list[EvalResult] = []
        for pair in qa_pairs:
            answer = agent_fn(pair.question)
            result = evaluator.run_full_eval(
                answer=answer,
                question=pair.question,
                context=pair.context or "",
                expected=pair.expected_answer,
                contexts=pair.retrieved_contexts,
            )
            result.qa_pair = pair
            results.append(result)
        return results

    def generate_report(self, results: list[EvalResult]) -> dict[str, Any]:
        total = len(results)
        if not total:
            return {
                "total": 0,
                "passed": 0,
                "pass_rate": 0.0,
                "avg_faithfulness": 0.0,
                "avg_relevance": 0.0,
                "avg_completeness": 0.0,
                "avg_context_recall": None,
                "avg_context_precision": None,
                "failure_types": {},
            }

        recalls = [r.context_recall for r in results if r.context_recall is not None]
        precisions = [r.context_precision for r in results if r.context_precision is not None]
        failures = Counter(r.failure_type for r in results if r.failure_type)
        passed = sum(1 for r in results if r.passed)
        return {
            "total": total,
            "passed": passed,
            "pass_rate": passed / total,
            "avg_faithfulness": sum(r.faithfulness for r in results) / total,
            "avg_relevance": sum(r.relevance for r in results) / total,
            "avg_completeness": sum(r.completeness for r in results) / total,
            "avg_context_recall": (sum(recalls) / len(recalls)) if recalls else None,
            "avg_context_precision": (sum(precisions) / len(precisions)) if precisions else None,
            "failure_types": dict(failures),
        }

    def run_regression(self, new_results: list[EvalResult], baseline_results: list[EvalResult]) -> dict[str, Any]:
        def avg(items: list[EvalResult], attr: str) -> float:
            if not items:
                return 0.0
            return sum(float(getattr(item, attr)) for item in items) / len(items)

        new = {name: avg(new_results, name) for name in ("faithfulness", "relevance", "completeness")}
        baseline = {name: avg(baseline_results, name) for name in ("faithfulness", "relevance", "completeness")}
        regressions = [name for name in ("faithfulness", "relevance", "completeness") if baseline[name] - new[name] > 0.05]
        return {
            "new_avg_faithfulness": new["faithfulness"],
            "new_avg_relevance": new["relevance"],
            "new_avg_completeness": new["completeness"],
            "baseline_avg_faithfulness": baseline["faithfulness"],
            "baseline_avg_relevance": baseline["relevance"],
            "baseline_avg_completeness": baseline["completeness"],
            "regressions": regressions,
            "passed": not regressions,
        }

    def identify_failures(self, results: list[EvalResult], threshold: float = 0.5) -> list[EvalResult]:
        return [
            result
            for result in results
            if any(score < threshold for score in (result.faithfulness, result.relevance, result.completeness))
        ]


class FailureAnalyzer:
    def categorize_failures(self, failures: list[EvalResult]) -> dict[str, int]:
        return dict(Counter(failure.failure_type or "unknown" for failure in failures))

    def find_root_cause(self, failure: EvalResult) -> str:
        scores = {
            "faithfulness": failure.faithfulness,
            "relevance": failure.relevance,
            "completeness": failure.completeness,
        }
        minimum = min(scores.values())
        lowest = [name for name, score in scores.items() if score == minimum]
        if len(lowest) != 1:
            return "Multiple issues detected — review full pipeline"
        if lowest[0] == "faithfulness":
            return "Context is missing or irrelevant — improve retrieval"
        if lowest[0] == "relevance":
            return "Answer does not address the question — improve prompt clarity"
        return "Answer is missing key information — increase context window or improve generation"

    def generate_improvement_suggestions(self, failures: list[EvalResult]) -> list[str]:
        if not failures:
            return []
        categories = self.categorize_failures(failures)
        suggestions: list[str] = []
        if categories.get("hallucination") or categories.get("Hallucination"):
            suggestions.append("Add grounding checks and require generated claims to be supported by retrieved context")
        if categories.get("irrelevant"):
            suggestions.append("Tighten intent-aware prompting so answers directly address the student's question")
        if categories.get("incomplete") or categories.get("Low_completeness"):
            suggestions.append("Improve retrieval coverage and prompt the generator to preserve required dates, conditions, and exceptions")
        if categories.get("off_topic"):
            suggestions.append("Add intent routing and an out-of-scope policy check before generation")
        if categories.get("refusal"):
            suggestions.append("Calibrate safety guardrails to distinguish unsupported requests from valid student-service questions")

        defaults = [
            "Tune retrieval chunking and top-k, then verify Context Recall and Context Precision on the golden dataset",
            "Add hard and adversarial regression cases for every recurring failure cluster",
            "Run the benchmark as a CI quality gate and block releases when core metrics regress by more than 0.05",
        ]
        for suggestion in defaults:
            if len(suggestions) >= 3:
                break
            if suggestion not in suggestions:
                suggestions.append(suggestion)
        return suggestions

    def generate_improvement_log(self, failures: list[EvalResult], suggestions: list[str]) -> str:
        def clean(value: Any) -> str:
            return str(value).replace("|", "\\|").replace("\n", " ")

        rows = [
            "| Failure ID | Type | Root Cause | Suggested Fix | Status |",
            "|------------|------|------------|---------------|--------|",
        ]
        for index, failure in enumerate(failures, start=1):
            suggestion = suggestions[index - 1] if index - 1 < len(suggestions) else "Review trace and remediate the identified root cause"
            rows.append(
                f"| F{index:03d} | {clean(failure.failure_type or 'unknown')} | "
                f"{clean(self.find_root_cause(failure))} | {clean(suggestion)} | Open |"
            )
        return "\n".join(rows)


if __name__ == "__main__":
    evaluator = RAGASEvaluator()
    runner = BenchmarkRunner()
    sample = [QAPair("What is AI?", "AI is artificial intelligence", "AI means artificial intelligence")]
    results = runner.run(sample, lambda _: "AI is artificial intelligence", evaluator)
    print(runner.generate_report(results))
