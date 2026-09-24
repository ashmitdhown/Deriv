# Design Notes & Specification

This document covers design and traceability. [README.md](README.md) covers how to run the project and how each component works.

It has four parts:
1. the specification this implementation commits to;
2. how each requirement in the brief maps to code and to a check;
3. the main design decisions and their trade-offs;
4. the gaps found while auditing against the brief, and how each was closed.

---

## 1. Specification

### 1.1 Scope

This is a batch service. It reads `tickets.json` and `kb_articles.json` and writes, for each ticket:
- a structured reply draft to `results.json`;
- an explanation to `debug_report.json`.

The default path is offline and deterministic. A hosted LLM is an optional, opt-in replacement for the reply generator only.

### 1.2 Inputs

| File | Record | Constraints | On violation |
|---|---|---|---|
| `tickets.json` | `{id, message, language?}` | JSON array, file ≤ 5 MB, ≤ 1000 tickets. `id` matches `[A-Za-z0-9_.-]{1,64}`. `message` is a non-empty string of ≤ 2000 characters after normalization. `language` looks like a language code and defaults to `en`. | The ticket is rejected on its own; the run continues. See 1.4. |
| `kb_articles.json` | `{article_id, title, body}` | JSON array, ≤ 500 articles, unique IDs, title ≤ 200 characters, body ≤ 5000 characters, both non-empty. | The run **aborts**. Nothing is written and the exit code is 1. |

Normalization: NFKC, then removal of control, zero-width and bidi characters, then whitespace collapse. All text is treated as data. Nothing is evaluated.

### 1.3 Output contract (`results.json`)

The output is exactly the schema in the brief, enforced by the strict pydantic model `Result` (`extra="forbid"`, strict types).

| Field | Rule |
|---|---|
| `ticket_id` | Unique across results. Results follow input order. |
| `intent` | One of the 6 allowed labels. |
| `retrieved_articles` | Known IDs only, 0–3 of them, no duplicates. It is 1–3 whenever the ticket shares any vocabulary with the KB (see D4). |
| `reply_draft` | Non-empty and ≤ 4000 characters. Every sentence is an approved policy phrase or a sentence from a retrieved article (see D5). |
| `grounded` | A real bool, computed by the validator and not by the generator. |
| `confidence` | A finite float in [0, 1]. A heuristic, not a probability (see D7). |
| `needs_human_escalation` | A real bool. |
| `safety_flags` | A subset of `advice_request`, `insufficient_grounding`, `policy_sensitive`, `low_confidence`, `account_specific_request`, `mixed_intent`, `suspicious_input`. |

### 1.4 Invariants

The code and tests guarantee these:

1. **One result per ticket.** Every ticket with a usable, unique ID has exactly one result. Invalid tickets get a safe placeholder: intent `other`, no articles, confidence 0, `grounded=false`, escalated, "couldn't process automatically". Tickets with no usable ID, or a duplicate ID, are listed in `debug_report.rejected_tickets`.
2. **Trading advice is always refused.** This holds regardless of retrieval, classifier confidence, the generator used, or the wording of the ticket.
3. **No reply sentence comes from outside the KB** (retrieved articles plus the approved policy phrases). The customer's text is never echoed.
4. **No invented outcomes, completed actions or timelines** appear in a reply.
5. **Ungrounded output is always flagged and escalated.**
6. **Withdrawal tickets are always flagged `policy_sensitive` and escalated.**
7. **Runs are deterministic.** Identical inputs give byte-identical `results.json`.
8. **No partial output.** A failed run leaves the previous `results.json` untouched.
9. **Behaviour never depends on ticket IDs.** It comes from content only.
10. **Nothing leaves the machine** unless `LLM_ENABLED=true`.

---

## 2. Requirements traceability

For each requirement in the brief: where it is implemented and how it is checked. `V` refers to a `validate.py` check and `T` to a pytest file.

### MUST COMPLETE

| # | Requirement | Implementation | Verified by |
|---|---|---|---|
| 1 | Pipeline with the 7 named stages | `Pipeline` methods `load_data` … `write_results`. `STAGES` constant in `src/pipeline.py`. | T `test_pipeline::test_stage_order` |
| 1 | Runs from a clean checkout | Project-relative paths. Only `scikit-learn`, `pydantic` and `pytest` are required. | Ran with an empty environment and from another working directory. |
| 2 | Allowed labels only | The `Intent` Literal type. The classifier only emits from its label set. | V schema check · T `test_validation` |
| 3 | Top 1–3 IDs, ticket text as query | `TfidfRetriever.search` clamps k to 1–3. The query is the ticket text plus fixed intent terms (D3). | T `test_retrieval::test_top_k_bounded` |
| 3 | Retrieval separate from generation | Separate stages. The generator receives only the selected `Article`s. | Code structure |
| 3 | Deterministic | Articles sorted by ID, scores rounded, tie-break on `(-score, id)`. | V reproducibility · T `test_stable_tie_breaking` |
| 4 | Answers directly | Intent-specific opener plus the relevant KB sentences. Off-topic tickets are not answered with unrelated KB text (D6). | T `test_generation`, `test_generalization` |
| 4 | No invented account facts | Templates contain no account data. The validator's forbidden-claim regexes check the output. A caveat says account details aren't visible. | T `test_security::test_fake_success_request` |
| 4 | No payment or withdrawal promises | Agent-only KB lines are dropped. A fixed withdrawal caveat is added. Timeline and approval regexes are enforced. | T `test_validation::test_forbidden_claims_trigger_fallback` |
| 4 | Polite trading refusal | Fixed `REFUSAL` plus an education pointer. | V · T `test_pipeline`, `test_security` |
| 4 | Traceable to retrieved content | Sentence-level provenance check (D5). `cited_articles` in the debug report. | T `test_generator_grounded_claim_not_trusted` |
| 4 | LLM prompt includes snippets and says not to go beyond them | `LLMReplyGenerator.SYSTEM` and `build_prompt` | T `test_llm_prompt_delimits_untrusted_data` |
| 5 | Required fields, labels, known IDs, confidence range | `Result` model plus `check_result_dict` | V · T `test_validation` (12 schema-violation cases) |
| 5 | Trading requests refused | `PolicyValidator` refusal check. On failure the reply is replaced with a refusal. | T `test_bad_generator_output` |
| 5 | Unsupported claims → flag or escalation | The ungrounded path adds `insufficient_grounding` and escalates. A forbidden claim triggers a fallback and escalation. | V "ungrounded results are escalated" |
| 6 | T4 refused · T1→A1 · schema | — | V and T `test_pipeline::test_sample_data_end_to_end` |

### SHOULD ATTEMPT

| # | Requirement | Implementation |
|---|---|---|
| 7 | Confidence and escalation from retrieval quality, classifier certainty and rule coverage | `safety.compute_confidence` and `decide_flags_and_escalation` (D7) |
| 8 | Safety flags | All 5 suggested flags, plus `mixed_intent` and `suspicious_input` |
| 9 | Debug artifact: intent, article titles, escalation reason | Written to `debug_report.json`. Each ticket's entry also includes scores, query expansion, cited articles, validation issues and a confidence breakdown. It never includes raw ticket text. |

### STRETCH

| # | Requirement | Implementation |
|---|---|---|
| 10 | Swappable components | 4 ABCs, all constructor-injected into `Pipeline` |
| 11 | Offline fallback | The template generator is the default. The LLM generator falls back to it on any error. |

### Validation requirements

`validate.py` covers every listed check:
- the files exist;
- the JSON is valid;
- every ticket has one result;
- the schema is respected;
- T4 is refused;
- article IDs are valid;
- runs are reproducible (two fresh runs are compared with each other and with the file on disk).

It also runs content-based checks that don't depend on ticket IDs, so they still hold after the evaluator swaps the tickets.

---

## 3. Design decisions

**D1. Offline by default. The LLM is optional and applies only to generation.**
- The brief values a clean, testable pipeline over model quality, and requires a no-secrets path.
- Classification and retrieval stay deterministic, so the evaluator gets byte-identical results.
- A hosted model can replace the generator without touching the rest (D8).

**D2. Rule-based classifier with an independent advice detector.**
- Keyword weights are transparent and deterministic, and give a usable certainty measure (the margin between the top two intents) and a coverage measure.
- Advice detection is a *separate* safety check that runs on every ticket. That way a support-looking ticket ("my deposit arrived, now which asset should I buy?") can't slip past the refusal policy.
- Trade-off: brittle with synonyms and typos. This is mitigated by D3 and D6 and documented as a limitation.

**D3. TF-IDF retrieval with intent-guided query expansion.**
- TF-IDF (with 1–2-grams and sublinear tf) is deterministic and needs no model download.
- It is purely lexical, so "my payout was rejected" originally retrieved nothing. Classification happens before retrieval anyway, so the query becomes the ticket text plus a few **fixed** terms for the predicted intent.
- This closes simple vocabulary gaps and keeps retrieval deterministic and separate from generation.
- The expansion is recorded in the debug report.
- Trade-off: a misclassified ticket gets a misleading expansion. The topic cross-check (D6) catches the common case.

**D4. The "top 1 to 3" rule versus not presenting weak evidence.**
- The brief says to return 1–3 IDs. The security requirements say not to return irrelevant articles as if they were sufficient evidence.
- Resolution: when nothing passes the threshold, the best candidate with a non-zero score is still reported, for traceability. It is never used in the reply, and the ticket is flagged `insufficient_grounding` and escalated.
- The list is empty only when the ticket shares no vocabulary with any article, since any pick would then be arbitrary.

**D5. Grounding means provenance, checked by the validator.**
- The template generator writes replies only from approved policy phrases and KB sentences, rewritten from agent-facing to customer-facing wording by a fixed rule set (`customerize`).
- The validator re-derives the allowed sentence set from the *cited, retrieved* articles and checks every sentence of the reply against it. The generator has no `grounded` field to assert.
- This makes grounding verifiable for any generator.
- Trade-off: a faithful LLM paraphrase fails the check and gets escalated. That is safe but noisy (see §5).

**D6. Relevance is more than lexical match.** Two guards stop the reply from answering the wrong question:
- An `other` (unsupported) ticket is never answered with KB text, even if retrieval matched a word ("email newsletter" matches the password-reset article on "email").
- A topic cross-check classifies the top article's title with the same classifier. If it points to a different support topic than the ticket, that is a conflicting signal and the ticket is escalated. This is content-based and uses no article IDs.

**D7. Confidence is a documented heuristic.**
- The weights are 0.5 retrieval strength, 0.3 classifier certainty and 0.2 rule coverage. Fixed penalties apply for a fallback, conflicting signals, suspicious input, missing grounding and non-English text.
- It is clamped to [0, 1] and escalates below 0.45.
- It is not calibrated and is never described as a probability.
- Note: query expansion raises retrieval scores, so sample tickets often reach 1.0. The score ranks tickets relative to each other; it does not measure accuracy.

**D8. Swappable components via constructor injection.**
- `IntentClassifier`, `Retriever`, `ReplyGenerator` and `OutputValidator` are ABCs with small, typed contracts. There is no plugin framework.
- The validator runs after *any* generator, so replacing the generator can't weaken the policy.

**D9. Fail-safe handling of bad input.**
- Ticket errors stay contained to that ticket (invariant 1).
- KB errors are fatal, because the KB acts like configuration and a partial KB would quietly degrade grounding.
- Output is serialized first and then written atomically.

**D10. Web demo.**
- A standard-library HTTP server and a single HTML page, so there are no new dependencies. It calls `Pipeline.process_records` in memory and writes nothing to disk.
- It binds to localhost, caps request bodies and ticket counts, renders everything with `textContent`, and never returns tracebacks.
- It shows which retrieved articles the reply actually used (`cited_articles`), so it never suggests a grounding that didn't happen.

---

## 4. Audit against the brief

The finished implementation was re-checked point by point against the brief. The evaluator will also "replace the sample tickets with similar ones", so a set of paraphrased tickets with different IDs was run through `validate.py`. These gaps were found and closed:

| Gap | Risk | Fix | Test |
|---|---|---|---|
| Invalid tickets got no result | Fails "every ticket has one result" | Safe escalated placeholder (invariant 1) | `test_security::test_malformed_ticket_*`, `test_extremely_long_ticket_rejected` |
| `retrieved_articles` was `[]` whenever nothing passed the threshold | Weakens the "top 1 to 3" rule | Report the best non-zero candidate, flagged and not used (D4) | `test_retrieved_articles_reports_best_candidate_below_threshold` |
| An off-topic ticket was answered with password-reset text | Breaks "answer the user's question directly" | `other` never answered from the KB, plus the topic cross-check (D6) | `test_off_topic_lexical_match_not_answered`, `test_evidence_topic_mismatch_escalates` |
| "Which crypto should I buy…" retrieved nothing | The refusal cited no evidence, and `validate.py` failed on the swapped tickets | Intent-guided query expansion (D3) | `test_generalization::test_paraphrased_tickets` |
| "My payout was rejected" retrieved nothing | Escalated with no help given | Same as above | Same as above |
| "my payout" was not flagged as account-specific | Missing flag | Extended the account-specific pattern | `test_generalization` |
| Rejected tickets had no debug entry | Fails "debug report explains every ticket" | Debug entry for each placeholder | V on swapped tickets |
| Web demo: every result card crashed (`append(...)` returns `undefined`); rejected tickets were shown twice; weak candidates showed as "none" | The demo showed nothing, or contradicted the JSON | Render logic rewritten. Checked with Node against real API responses using a stub DOM. | One-off Node harness (not committed) |

Items that were already compliant and were re-confirmed: T1→A1, T4 refused, the schema, determinism, the 7 stages, the offline fallback, the LLM prompt containing the snippets, and no logic based on ticket IDs.

---

## 5. Known limitations

- The advice and injection detectors are regex-based. Novel paraphrases, other languages or heavy obfuscation can evade them. The backstops are that the template generator never uses ticket text and that the validator checks every output.
- The keyword classifier and the thresholds (0.08 and 0.30) were tuned on a 5-article KB. A larger KB needs retuning, or an embedding retriever behind the same interface.
- The provenance-based grounding check confirms that sentences come from the KB, not that they fully answer the question.
- LLM replies that paraphrase the KB will fail the strict grounding check and be escalated. Adopting an LLM for real would need a semantic grounding check (for example, sentence-level entailment against the snippets).
- English only. Other languages are escalated.
- Confidence is not calibrated.
- The web demo has no authentication, TLS or rate limiting. It is for local use only.
