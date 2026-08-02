# Evidence Appendix Executive Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace scattered body citations with a final reverse-mapped Evidence Appendix and remove Risk Flags and Targeted Recommendations from the case-review output contract.

**Architecture:** Keep the internal claim-to-evidence ledger and evidence gate unchanged in strength, but separate internal traceability from rendered presentation. The body becomes an executive narrative with no evidence markers; a final five-column appendix maps evidence rows back to exact body conclusions through the Supports column.

**Tech Stack:** Markdown skill contract, paired Markdown/HTML documentation, Python `unittest`, JSON scenario fixtures, Git.

---

## File Responsibilities

- `plugins/avaya-case-review/skills/case-review/SKILL.md`: canonical runtime workflow and rendered report template.
- `tests/test_case_review_contract.py`: static contract, ordering, absence, parity, and release-state validators.
- `tests/case_review_scenarios.json`: scenario-level expected behavior and contract-marker coverage.
- `README.md` / `README.html`: top-level public summary of the current report contract.
- `docs/MANAGER_ONBOARDING_GUIDE.md` / `.html`: manager-facing report description.
- `docs/TECHNICAL_DESIGN_DOCUMENT.md` / `.html`: technical contract and validation design.
- `docs/RELEASE_NOTES.md` / `.html`: Unreleased behavioral change record.

### Task 1: Lock the New Output Contract with Failing Tests

**Files:**
- Modify: `tests/test_case_review_contract.py`
- Modify: `tests/case_review_scenarios.json`

- [ ] **Step 1: Replace the old inline-evidence assertions**

Add a helper that extracts the fenced rendered template:

```python
def extract_report_template(skill: str) -> str:
    match = re.search(r"\`\`\`markdown\n(.*?)\n\`\`\`", skill, re.DOTALL)
    if not match:
        raise AssertionError("Rendered report template not found")
    return match.group(1)
```

Replace the old documentation markers with:

```python
required = [
    "Appendix A — Evidence Register",
    "| Ref | Date | Source | Verbatim evidence / data | Supports |",
    "Ownership & Next Step",
]
prohibited = ["Risk Flags", "Targeted Recommendations"]
```

- [ ] **Step 2: Add body-cleanliness and section-order tests**

```python
def test_appendix_is_last_and_body_has_no_evidence_markers(self):
    template = extract_report_template(self.skill)
    appendix = template.index("## Appendix A — Evidence Register")
    order = [
        template.index("## Verdict"),
        template.index("## Technical & Incident Assessment"),
        template.index("## Progress Summary"),
        template.index("## Ownership & Next Step"),
        template.index("## Timeline"),
        appendix,
    ]
    self.assertEqual(order, sorted(order))
    body = template[:appendix]
    self.assertNotRegex(body, r"\[(?:Evidence\s+\d+|E\d+)\]|Evidence IDs?|Evidence N")
    self.assertTrue(template.rstrip().endswith("<Evidence rows E1..EN>"))

def test_manager_judgment_sections_are_absent(self):
    template = extract_report_template(self.skill)
    self.assertNotIn("## Risk Flags", template)
    self.assertNotIn("## Targeted Recommendations", template)
    self.assertIn("must never generate a new recommendation", self.skill)
```

- [ ] **Step 3: Update scenario expectations**

Change the multi-problem scenario expectation to:

```json
{
  "id": "multi_problem_case",
  "expected": "Use the multi-problem structure, make no recommendations, and reverse-map all supporting evidence in the final appendix.",
  "contract_markers": [
    "multi-problem assessment",
    "Appendix A — Evidence Register",
    "must never generate a new recommendation"
  ]
}
```

Add:

```json
{
  "id": "appendix_reverse_mapping",
  "input": "Several body conclusions are supported by overlapping case and Gmail evidence.",
  "expected": "Keep the body citation-free and map each appendix row back through the Supports column.",
  "contract_markers": [
    "body must contain no Evidence IDs",
    "Supports",
    "final section"
  ]
}
```

- [ ] **Step 4: Run tests and verify RED**

Run:

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONDONTWRITEBYTECODE='1'
python -m unittest tests.test_case_review_contract -v
```

Expected: failures for missing appendix-last layout, inline body Evidence IDs, and still-present Risk Flags/Targeted Recommendations.

### Task 2: Implement the Canonical SKILL Contract

**Files:**
- Modify: `plugins/avaya-case-review/skills/case-review/SKILL.md`
- Test: `tests/test_case_review_contract.py`

- [ ] **Step 1: Keep the internal ledger but change rendered references**

Change ledger IDs to `E1..EN` and retain Source, Date, Verbatim evidence/data, and Supports. Add these exact rules:

```markdown
- The rendered body must contain no Evidence IDs, footnotes, source suffixes, or citation brackets.
- Every factual body claim must still map internally to at least one appendix row.
- The Supports column performs reverse mapping from evidence to the exact body conclusion.
```

- [ ] **Step 2: Remove recommendation and risk-generation logic**

Delete:

- the Reflection rule requiring every risk to have an action;
- the `Risk Flags` output section;
- both `Targeted Recommendations` subsections;
- all instructions to cite evidence beside verdicts, ownership, timeline, or actions.

Add:

```markdown
- Ownership & Next Step may only restate actions, owners, and dates already present in case-specific evidence.
- It must never generate a new recommendation, owner, deadline, risk score, or risk list.
```

- [ ] **Step 3: Replace the rendered template**

Use this exact section skeleton:

```markdown
# Case Review - <Case ID>
<Case header fields>

## Verdict
<Evidence-supported verdict with no citation marker>

## Technical & Incident Assessment
<Exactly one single-issue or multi-problem structure>

## Progress Summary
<Three to five substantive milestones>

## Ownership & Next Step
<Evidence-stated owner, action, and date fields only>

## Timeline
| Date | By | Source | What changed |
|---|---|---|---|
<Substantive entries>

## Appendix A — Evidence Register
| Ref | Date | Source | Verbatim evidence / data | Supports |
|---|---|---|---|---|
<Evidence rows E1..EN>
```

- [ ] **Step 4: Run targeted tests and verify GREEN**

Run:

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONDONTWRITEBYTECODE='1'
python -m unittest tests.test_case_review_contract.CaseReviewContractTests.test_appendix_is_last_and_body_has_no_evidence_markers tests.test_case_review_contract.CaseReviewContractTests.test_manager_judgment_sections_are_absent -v
```

Expected: both tests pass.

### Task 3: Align Public and Technical Documentation

**Files:**
- Modify: `README.md`
- Modify: `README.html`
- Modify: `docs/MANAGER_ONBOARDING_GUIDE.md`
- Modify: `docs/MANAGER_ONBOARDING_GUIDE.html`
- Modify: `docs/TECHNICAL_DESIGN_DOCUMENT.md`
- Modify: `docs/TECHNICAL_DESIGN_DOCUMENT.html`
- Modify: `docs/RELEASE_NOTES.md`
- Modify: `docs/RELEASE_NOTES.html`
- Test: `tests/test_case_review_contract.py`

- [ ] **Step 1: Update README contract summaries**

State that the main body is citation-free, Evidence appears only in the final Appendix A table, and Managers own risk/action judgment. Remove current claims that all actions appear in Targeted Recommendations.

- [ ] **Step 2: Update Manager Onboarding MD and HTML**

Describe the seven-section order and the five-column appendix. Remove current Risk Flags and Targeted Recommendations entries.

- [ ] **Step 3: Update Technical Design MD and HTML**

Document internal claim mapping versus rendered reverse mapping. Remove Risk Flags and Targeted Recommendations from the current output schema while leaving historical release records intact.

- [ ] **Step 4: Add an Unreleased Release Notes entry**

Add above v1.4.0:

```markdown
## [Unreleased]

### Executive Report Readability Redesign

- Moves all rendered evidence into a final reverse-mapped Evidence Appendix.
- Removes inline Evidence annotations from the body.
- Removes Risk Flags and Targeted Recommendations so Managers retain judgment ownership.
```

Add the equivalent HTML block.

- [ ] **Step 5: Run documentation parity tests**

Run:

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONDONTWRITEBYTECODE='1'
python -m unittest tests.test_case_review_contract.CaseReviewContractTests.test_current_contract_docs_match_skill tests.test_case_review_contract.CaseReviewContractTests.test_distributable_docs_have_no_machine_specific_file_urls -v
```

Expected: both tests pass.

### Task 4: Full Verification and Review

**Files:**
- Verify: all modified files

- [ ] **Step 1: Run the complete contract suite**

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONDONTWRITEBYTECODE='1'
python -m unittest tests.test_case_review_contract -v
```

Expected: all tests pass.

- [ ] **Step 2: Validate whitespace and links**

```powershell
git diff --check
```

Expected: exit code 0.

Run the existing Python local-link and HTML parsing validator used by the v1.4.0 release checks. Expected: zero broken local links and all HTML files parse.

- [ ] **Step 3: Audit forbidden current-contract patterns**

```powershell
rg -n "## Risk Flags|## Targeted Recommendations|\[Evidence [0-9N]+\]|\[E[0-9]+\]" plugins/avaya-case-review/skills/case-review/SKILL.md README.md README.html docs/MANAGER_ONBOARDING_GUIDE.* docs/TECHNICAL_DESIGN_DOCUMENT.*
```

Expected: no matches in current output templates or current-contract documentation.

- [ ] **Step 4: Review the final diff**

Confirm:

- Appendix is last;
- body citations are absent;
- Risk Flags and Targeted Recommendations are absent;
- Ownership only restates evidence-stated next steps;
- v1.4.0 historical notes remain unchanged;
- new work is recorded under Unreleased.

- [ ] **Step 5: Commit the implementation**

```powershell
git add plugins/avaya-case-review/skills/case-review/SKILL.md tests/case_review_scenarios.json tests/test_case_review_contract.py README.md README.html docs/MANAGER_ONBOARDING_GUIDE.md docs/MANAGER_ONBOARDING_GUIDE.html docs/TECHNICAL_DESIGN_DOCUMENT.md docs/TECHNICAL_DESIGN_DOCUMENT.html docs/RELEASE_NOTES.md docs/RELEASE_NOTES.html docs/superpowers/plans/2026-08-02-evidence-appendix-report.md
git commit -m "feat(case-review): move evidence to report appendix"
```

Expected: one local implementation commit. Do not push or publish without explicit user authorization.
