# Durable Case Record and Learning Lifecycle

Use this contract after the current review has passed Complete Context Before Analysis and the evidence gate. The durable record improves continuity; it never replaces fresh source collection.

## Invariants

- Keep one persistent directory per normalized primary Case ID.
- Treat the prior record only as a comparison baseline. Never cite it as current case evidence and never let it widen the primary-ID-only Gmail query.
- Recollect CaseToMD and Gmail under a new shared snapshot for every review, including a follow-up on the same SR.
- Update the record only after all current-run coverage equalities pass and at least one case-specific evidence item supports the review.
- If collection or evidence validation fails, leave the existing record byte-for-byte unchanged.
- Preserve every successful review as an append-only compact history entry while replacing the current card, current evidence digest, and current structured ReviewSnapshot v2.
- Keep official administrative status, RCA state, mitigation maturity, and production outcome as separate fields.
- Require new reviews to record customer impact and concrete investigation progress separately; older saved snapshots render missing fields as `unknown` without changing their history.

## Storage

Use the bundled `scripts/case_record.py` helper. It writes a machine record and a human record outside the installed plugin so upgrades do not erase follow-up history.

- Windows default: `%LOCALAPPDATA%\AvayaCaseReview\case-records\<CASE-ID>\record.json` and `record.md`
- Other platforms: `$XDG_DATA_HOME/avaya-case-review/` or `~/.local/share/avaya-case-review/`
- Optional override: `CASE_REVIEW_DATA_DIR`

Resolve an existing record without opening it before current-run analysis:

```text
python <skill-directory>/scripts/case_record.py paths --case-id <primary raw Case ID>
```

Reading prior conclusions before completing the fresh analysis creates anchoring risk. Let the helper compare the newly completed state with the stored state.

## Successful Review Update

Create a temporary UTF-8 JSON payload only after the current structured analysis is complete. Follow [output-modes.md](output-modes.md) and run:

```text
python <skill-directory>/scripts/case_record.py finalize-overlay --manifest <manifest.json> --overlay <overlay.json> --case-id <Case ID> --request "<original user request>"
```

The v2 payload retains the verified coverage, current state, and decisive evidence digest, then adds a structured `presentation` object:

```json
{
  "case_id": "1-23700000001",
  "reviewed_at": "2026-08-20T03:00:00Z",
  "snapshot_before": "2026-08-20T02:59:00Z",
  "collection_status": "complete",
  "coverage": {
    "case_notes_discovered": 10,
    "case_notes_processed": 10,
    "record_ids_planned": 1,
    "record_id_queries_completed": 1,
    "query_complete": true,
    "unique_threads_discovered": 2,
    "threads_read_complete": 2,
    "messages_expected": 5,
    "messages_completed": 5,
    "message_chunks_expected": 5,
    "message_chunks_completed": 5,
    "body_hashes_verified": 5,
    "manifest_hashes_stable": 2,
    "snapshot_before": "2026-08-20T02:59:00Z"
  },
  "current": {
    "title": "Evidence-backed title or unknown",
    "source": "Siebel SR",
    "official_status": "In Progress",
    "priority": "P2",
    "assignee": "Name or unknown",
    "primary_problem": "Concise primary problem",
    "impact": "One plain-language impact statement, or unknown",
    "current_progress": "Work completed, trace or log findings, and validation gap, or unknown",
    "confirmed_finding": "One plain-language confirmed finding, or unknown",
    "unproven_or_contradicted": "Material unsupported or contradicted claim",
    "rca_state": "Under Investigation",
    "mitigation_state": "None Active",
    "production_outcome": "unknown",
    "current_blocker": "Exact blocker or unknown",
    "next_action": "Evidence-stated action or not stated",
    "next_action_owner": "Name, unassigned, or unknown",
    "next_due": "Date, not stated, or unknown"
  },
  "evidence_digest": [
    {
      "state": "OBSERVED",
      "date": "2026-08-19T10:00:00Z",
      "source": "Case activity or log",
      "fact": "One decisive, faithfully transcribed fact"
    }
  ],
  "presentation": {
    "technical_advice": {
      "immediate_diagnostics": [],
      "potential_solutions": [],
      "long_term_steps": []
    },
    "technical_spec": {
      "scope": {
        "state": "OBSERVED",
        "value": "Affected environment and scope",
        "evidence": "Evidence basis"
      }
    },
    "problem_lineage": {
      "original_objective": "Original objective",
      "intended_action": "Intended action",
      "blocker": "Current blocker",
      "working_hypotheses": ["Evidence-labeled hypothesis"],
      "corrected_finding": "Corrected finding or unknown",
      "implemented_action": "Implemented action or none",
      "outcome": "Evidence-backed outcome",
      "secondary_problems": []
    },
    "milestones": [],
    "timeline": [],
    "evidence_register": [
      {
        "ref": "E1",
        "date": "2026-08-19T10:00:00Z",
        "source": "Case activity or log",
        "evidence": "Verbatim evidence",
        "supports": "Exact structured field"
      }
    ],
    "visual_context": {}
  }
}
```

Populate all twelve Technical Specification fields defined in `output-modes.md`; the abbreviated example above shows only `scope`. Every new payload requires the three `technical_advice` arrays even when they are empty. An immediate or long-term item has `action` and `basis`; a potential solution also has `condition`. Tie each `basis` to case evidence or a precise missing validation item, and render each step in a separate Technical Advice section rather than as completed work. `current.next_action` remains the documented commitment in the Case Card's Action Plan, with its separate owner and due date. `finalize` and `finalize-overlay` require structured `presentation` and reject `full_review_markdown` alone before changing the record; legacy `update` still accepts that field for compatibility.

The helper validates coverage and schema, migrates a v1 record without losing its history or legacy report, computes deltas, appends one history entry, and atomically rewrites the current Markdown view. Reusing the same completed snapshot and state is idempotent.

## Deterministic Chat Response

Use `case_record.py finalize-overlay` after every successful evidence-gated analysis. It assembles the manifest and overlay, validates and prepares the record update, renders from the resulting snapshot, writes the record plus canonical `chat-output.md` and `chat-output.sha256` files, internally verifies the artifact, and emits only the Markdown intended for chat. Validation and rendering occur before durable files are replaced, and the full operation runs under one per-case lock. Every successful structured artifact begins with:

```markdown
# Case Review - 1-23700000001

## Executive Summary

- **Status:** In Progress — **Reported issue:** Concise primary problem
- **Impact:** Evidence-backed impact or unknown
- **Critical finding:** Evidence-backed finding or unknown
- **Production outcome:** unknown

## Case Card
```

Return the exact `finalize-overlay` stdout without alteration. The command verifies the stored artifact hash and canonical bytes internally before it succeeds. The backward-compatible `case_record.py update`, `case_record.py present --markdown-only`, and `case_record.py verify-final` commands remain supported for existing integrations and diagnostics; `verify-final` continues to tolerate line-ending and final-newline transport differences while rejecting content or structure drift.

Do not manually recreate, shorten, expand, or append to the Executive Summary, Case Card, Action Plan, Technical Advice, delta, Investigation Progress flow, Causal Assessment, Technical Specification, Timeline, Evidence Register, or full report. The renderer selects investigation-complete `standard` for a first or unchanged plain review, investigation-complete `follow-up` for a materially changed later review, and `compact` only for an explicit compact request. It applies the secondary diagnostic-visual thresholds from `output-modes.md`.

If persistence fails after a valid review, say `Case record update failed` with the sanitized failure and do not claim the record was saved. The evidence-grounded review remains valid, but continuity is not complete until the write succeeds.

## Administrative Closure and Learning

An official status such as Closed, Resolved, or Completed sets the record's administrative state to `closed`. It does not change RCA or production outcome. A closed record always exposes a learning option, even when the only reusable learning is a diagnostic limitation or negative-evidence pattern.

If a later fresh review shows that the case reopened, mark the record `reopened`, continue follow-up, and suspend any previously applied overlay entry from that case. It must be reviewed and explicitly approved again after a later closure.

When the user explicitly asks `Learn from <Case ID>`:

1. Ensure the record's latest run passed the complete-context and evidence gates and captured the closure. Refresh the review first if closure was not collected in that run.
2. Generalize only what the evidence supports. Remove customer names, email addresses, hostnames, tenant/site identifiers, raw logs, and case-specific values from the reusable content.
3. Classify the candidate as `verified-pattern`, `diagnostic-heuristic`, `negative-evidence`, or `operational-check`, and retain evidence strength as `Validated`, `Identified`, or `Suspected`.
4. Include activation conditions, diagnostic steps, disconfirming signals, and limitations. A suspected pattern must stay labeled Suspected.
5. Create the candidate JSON and run `draft-learning`. Show the generated Markdown candidate to the user.
6. Stop for explicit approval unless the user's current request already explicitly authorizes applying the displayed candidate.

```text
python <skill-directory>/scripts/case_record.py draft-learning --input <candidate.json>
```

Candidate shape:

```json
{
  "case_id": "1-23700000001",
  "domain": "contact-center",
  "title": "Generalized diagnostic title",
  "learning_type": "diagnostic-heuristic",
  "evidence_strength": "Identified",
  "generalized_finding": "Reusable finding without customer-specific data",
  "activation_conditions": ["Condition that activates this guidance"],
  "diagnostic_steps": ["Evidence-driven validation step"],
  "disconfirming_signals": ["Observation that weakens this pattern"],
  "limitations": ["Boundary that prevents overgeneralization"],
  "customer_data_removed": true
}
```

After explicit approval, apply it:

```text
python <skill-directory>/scripts/case_record.py apply-learning --case-id <Case ID> --approved-by-user
```

The helper writes an approved local overlay under `domain-knowledge/<domain>.md`. On future matching reviews, locate it with `knowledge-path`, read it after the packaged reference, and treat it as diagnostic guidance rather than case proof. Plugin upgrades preserve this local overlay.

Applying a candidate updates only the user's local knowledge overlay. Promotion into the shared packaged reference requires a separate repository change and review.
