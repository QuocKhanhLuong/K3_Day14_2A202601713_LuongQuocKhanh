# Day 14 — Exercises

## AI Evaluation & Benchmarking · Lab Worksheet

**Domain:** Northstar University Student Services

---

## Part 1 — Warm-up

### Exercise 1.1 — RAGAS Metric Thresholds

| Metric | Acceptable Low Score Scenario | Critical Low Score Scenario | Action Required |
|---|---|---|---|
| Faithfulness | A cautious answer explicitly says evidence is insufficient instead of inventing a policy; lexical overlap can be low even though behavior is safe. | The answer states an unsupported policy, deadline, amount, condition, or exception as fact. | Inspect gold/retrieved context; strengthen grounding instructions and add unsupported-claim checks. |
| Answer Relevance | A multi-part policy answer may contain necessary procedural detail that shares few words with a short question. | The answer solves a different intent or discusses an unrelated student-service topic. | Improve intent-aware prompting/routing and add direct-answer checks. |
| Context Recall | Low recall is only tolerable when the missing text is redundant and the retrieved evidence still fully supports a safe answer. | Required evidence for a date, amount, exception, or eligibility condition is missing. | Improve query formulation, chunking, top-k, and retrieval coverage tests. |
| Context Precision | Some noise is tolerable when all required evidence still appears early enough and context budget is not constrained. | Relevant evidence is buried behind noise so the generator misses it or context budget is wasted. | Add reranking, tune top-k, and improve chunk boundaries. |
| Completeness | A concise answer may omit optional explanation while still answering the requested decision/action. | A required condition, date, amount, exception, or next step is omitted. | Check retrieval coverage and prompt the generator to preserve all required conditions/exceptions. |

### Exercise 1.2 — Bias trong LLM-as-a-Judge

**Câu 1: Thiết kế experiment phát hiện position bias với ít nhất hai conditions.**

> Build paired comparisons using the same question and two fixed answers A/B. Condition 1 presents A first and B second; Condition 2 swaps the order while changing nothing else. Repeat over multiple questions and randomize which quality level is assigned to A/B. Position bias is indicated when the first position receives a systematically higher score after controlling for answer content. A stronger protocol repeats the swap with multiple judge seeds/models and reports the paired score difference.

**Câu 2: Làm thế nào giảm verbosity bias bằng rubric design?**

> Score correctness, required conditions, evidence support, and actionability explicitly rather than rewarding detail or length. State that additional text earns no credit unless it adds required information, and that unsupported/redundant claims can reduce the score. A concise complete answer and a long complete answer should therefore receive the same maximum score.

**Câu 3: Tại sao cần calibrate LLM judge với human labels?**

> Human labels provide an external reference for detecting systematic leniency, severity, self-preference, and category-specific mistakes. Calibration lets us estimate agreement, tune score thresholds, refine ambiguous rubric wording, and avoid treating a judge's internally consistent bias as ground truth.

### Exercise 1.3 — Evaluation trong CI/CD

**Câu 1: Chọn threshold để block deployment.**

| Metric | Threshold | Lý do |
|---|---:|---|
| Faithfulness | 0.80 | Student-service answers contain policy, money, and deadline claims; unsupported claims are high-risk and should block release. |
| Answer Relevance | 0.70 | The assistant must address the user's actual intent; moderate lexical variation is acceptable. |
| Completeness | 0.70 | Missing a material condition/exception can make an otherwise correct answer operationally wrong. |

**Câu 2: Khi nào dùng offline evaluation, online evaluation và human review?**

> Use offline evaluation for every code, prompt, retrieval, or corpus change before release; it is repeatable and works as a CI quality gate. Use online evaluation after deployment on real traffic to detect distribution shift, latency/cost issues, and new failure patterns. Use human review for high-stakes or ambiguous policy cases, adversarial/safety calibration, and periodic validation of the LLM judge.

---

## Part 2 — Core Coding

Completed in `template.py` and copied to `solution/solution.py`.

Implemented:

- `QAPair`, `EvalResult`, and three-metric `overall_score()`.
- Faithfulness, Relevance, Completeness, Context Recall, rank-aware Context Precision.
- `run_full_eval(..., contexts=None)` with retrieval metrics kept diagnostic only.
- `LLMJudge.score_response()` and bias detection.
- `BenchmarkRunner` including retrieval wiring, aggregate report, regression detection (>0.05), and failure filtering.
- `FailureAnalyzer` including failure clustering, root-cause suggestions, and improvement log.
- Bonus `rerank_by_overlap()`.

Public CI result: **42/42 tests passed**, including the reranking bonus test.

---

## Part 3 — Golden Dataset & Real Benchmark

### Exercise 3.1 — Build the Golden Dataset

| Hạng mục | Kết quả |
|---|---|
| Tổng số records | 20 / 20 |
| Easy | 5 / 5 |
| Medium | 7 / 7 |
| Hard | 5 / 5 |
| Adversarial | 3 / 3 |
| Source documents được sử dụng | 10 / 10 |
| Validator status | **PASS** |

**Ba case đại diện cho quyết định thiết kế**

| ID | Difficulty | Source document(s) | Vì sao case phù hợp với difficulty/attack type? |
|---|---|---|---|
| E01 | Easy | `01_academic_calendar.md` | Single-document factual lookup with explicit Fall 2026 add/drop and census dates. |
| H01 | Hard | `09_privacy_security_and_policy_updates.md`, `01_academic_calendar.md`, `02_course_registration.md` | Requires policy-version reasoning, event date, term-specific dates, approvals, and fee conditions across documents. |
| A02 | Adversarial | `00_system_scope.md` | Direct prompt-injection attempt asking the system to override rules, reveal hidden material, and request a one-time code. |

**Điểm khó nhất khi xây dựng expected answer hoặc evidence là gì?**

> The hardest part was keeping every expected-answer claim traceable to verbatim corpus evidence while still making Hard cases require multi-document reasoning. In particular, effective-date/version cases must use the event-date rule instead of simply choosing the newest-looking text. I therefore kept expected answers concise and included separate evidence snippets for each material date, amount, condition, or exception.

**Xác nhận:**

- [x] Mọi claim trong expected answer đều có evidence hỗ trợ.
- [x] Không có questions trùng ý và không dùng kiến thức ngoài corpus.
- [x] `python validate_golden_dataset.py` báo `PASS`.

### Exercise 3.2 — Benchmark Run

The benchmark table is intentionally filled from **real** `domain_assistant.py` output, not invented values. Run:

```bash
python domain_assistant.py
python evaluate_answers.py
```

`evaluate_answers.py` writes `artifacts/benchmark_results.json` and prints all 20 rows, aggregate metrics, failure distribution, and the three lowest-scoring cases. The repository includes an automated real-benchmark workflow so this section can be regenerated from the actual artifact without gold leakage.

**Interpretation rule used after the run:**

- Low Context Recall + low Completeness → retrieval likely missed required evidence.
- High Recall + low Precision → evidence is present but ranking/noise is weak.
- Good retrieval + low Faithfulness → generation added unsupported claims.
- High Faithfulness + low Relevance → grounded answer, wrong intent.

### Exercise 3.3 — LLM-as-a-Judge Rubric Design

Selected dimensions: **Correctness, Completeness, Relevance/Actionability, Evidence grounding, Safety/Privacy**.

| Score | Tiêu chí domain-specific | Ví dụ response |
|---:|---|---|
| 5 | Fully correct and grounded; answers the exact intent; preserves every material date, amount, condition, and exception; gives the appropriate next step; no privacy/safety violation. | States the exact deadline and exception, cites/uses supported policy conditions, and directs the student to the correct office when needed. |
| 4 | Correct on all material policy points with only a minor non-material omission or wording issue; no unsupported policy claim or safety issue. | Correct deadline/eligibility and action, but omits a helpful explanatory detail. |
| 3 | Core direction is correct but one important condition, exception, date, or action is missing/unclear; no severe safety breach. | Says a late add is possible but omits one required approval or payment timing. |
| 2 | Significant factual/procedural error, wrong amount/deadline, major missing condition, unsupported claim, or weak privacy handling. | Gives the right office but an incorrect filing window or invents an exception. |
| 1 | Wrong/irrelevant answer, fabricated policy, unsafe disclosure/credential request, or failure to reject a prohibited/out-of-scope request. | Reveals private information, asks for a one-time code, or confidently invents a policy. |

**Ba edge cases khó chấm**

| Edge Case | Tại sao khó chấm? | Rubric xử lý thế nào? |
|---|---|---|
| Correct main rule but missing an exception | Surface answer looks correct but can cause a wrong decision. | Cap at 3 when a material exception/condition is missing. |
| Assistant says evidence is insufficient | May look incomplete but can be the safest grounded behavior. | Do not penalize as hallucination; score correctness/safety high if corpus truly lacks evidence, while completeness reflects what was answerable. |
| Long answer with correct core plus unsupported extras | Verbosity can fool a judge. | Unsupported material claims reduce Correctness/Evidence; length itself gives no bonus. |

**Bias controls**

> Randomize answer order for pairwise judging; use a length-neutral rubric with explicit required facts; penalize unsupported extra claims; calibrate against human labels; periodically use a second judge/model; and review disagreement cases rather than trusting a single scalar score.

### Exercise 3.4 — Framework Comparison (Bonus +10)

Comparison design uses the **same 20 Northstar questions, expected answers, gold contexts, actual answers, and retrieved traces**.

| Tiêu chí | Framework 1: RAGAS | Framework 2: DeepEval |
|---|---|---|
| Setup complexity | Evaluation dataset + RAG-specific metric objects; best when traces/contexts are already structured. | Test-case objects + metric assertions; straightforward for Python/pytest workflows. |
| Metrics available | Strong RAG-oriented diagnostics such as faithfulness, answer relevancy, context recall/precision. | LLM evaluation metrics plus test-style assertions for answer/retrieval quality and custom criteria. |
| CI/CD integration | Suitable for batch/offline evaluation; thresholds can be converted into a release gate. | Particularly natural for pytest-style pass/fail CI assertions. |
| Kết quả trên cùng dataset | Use the same 20 inputs and compare normalized metric trends/failure IDs, not raw numbers only. | Use identical inputs and thresholds mapped to the same semantic criteria. |
| Insight rút ra | Better diagnostic view of *where* a RAG pipeline fails (retrieval vs generation). | Better developer ergonomics when evaluation should behave like automated unit/integration tests. |

> Exact scores need not be numerically identical because framework prompts, judge models, and metric definitions differ. The meaningful comparison is whether both identify the same high-risk failure clusters and whether ranking of bad cases is stable. I would treat RAGAS as the richer RAG diagnostic layer and DeepEval as the more convenient test/CI assertion layer, rather than claiming one universal score is “truer.”

### Exercise 3.5 — Retrieval Reranking (Bonus +5)

Implemented `rerank_by_overlap()` and `bonus_rerank.py`. The script evaluates **all 20 traces** (therefore satisfying the ≥5 requirement), preserves the exact chunk set, and writes `artifacts/bonus_rerank_results.json`.

```bash
python bonus_rerank.py
```

**Tại sao Recall dự kiến không đổi?**

> Context Recall is computed over the union of tokens in the retrieved chunks. Reranking changes only order, not membership, so the union is identical. Context Precision is rank-aware, so moving relevant chunks earlier can increase it.

**Khi nào reranking không đủ và cần sửa retriever/query/chunking?**

> Reranking cannot recover evidence that was never retrieved. If Context Recall is low because the required source/chunk is absent from top-k, the fix must target retrieval coverage: query expansion, metadata/effective-date filters, BM25/embedding/hybrid retrieval, larger or better-formed chunks, or a different top-k. Reranking is mainly appropriate when recall is already adequate but relevant chunks are ordered behind noise.

---

## Completion Checklist

- [x] All required + bonus public tests pass (42/42).
- [x] `golden_dataset.json` validates: 20 QA, 10/10 source coverage.
- [x] Exercise 3.1 complete.
- [ ] Exercise 3.2 numeric table is generated from the real OpenAI run artifact.
- [x] Exercise 3.3 rubric and bias controls complete.
- [ ] `reflection.md` numeric/trace-specific fields are finalized after the same real benchmark run.
- [x] `solution/solution.py` exists.
- [x] Exercise 3.4 framework comparison complete.
- [x] Exercise 3.5 reranking implementation complete; measurements run after actual traces exist.
