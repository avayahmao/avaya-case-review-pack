# Executive Summary and Technical Assessment Deduplication — Executed Record

- **Status:** Completed
- **Executed:** 2026-08-04
- **Pre-implementation base:** `aec2139`
- **Completion head before this record fix:** `0859fce`

> **Record note:** Command blocks and `Expected:` lines are retained to preserve the original test-first intent. Completed checkboxes and the Execution Record capture the outcomes that were actually achieved.

**Goal:** Replace the overlapping field-by-field Executive Summary with one 6-8 sentence management/technical paragraph while making Technical & Incident Assessment the exclusive home for detailed reasoning, ADM depth, and Existing prevention controls whose implementation is confirmed by evidence.

**Architecture:** Treat the technical assessment as the source of the report's technical conclusion, then extract only conclusion-level facts into the Executive Summary. Enforce the boundary through the canonical SKILL contract, scenario fixtures, static contract tests, synchronized user documentation, and a final deployed-runtime comparison.

**Tech Stack:** Markdown skill contract, Python `unittest`, JSON scenario fixtures, paired Markdown/HTML documentation, PowerShell runtime deployment checks.

---

## Working Tree Constraint

Work began with approved, uncommitted changes for chronological ordering, the `unknown` evidence fallback, Executive Summary migration, and optional Apps Script cleanup. Those edits were preserved rather than reset or replaced, staged only with their assigned files, and captured by the commits below. The Apps Script optionalization dependencies were committed before final runtime verification, leaving the completed checkout self-contained.

## Execution Record

| Task | Commits | Recorded outcome |
|---|---|---|
| Task 1 — Canonical contract | `b2f4219`, `97d5a0e`, `e4ac4fd` | Layered Executive Summary, technical-depth, ADM activation, and prevention-boundary safeguards completed. |
| Task 2 — Core documentation | `0074e35`, `515dad7`, `6b3c58a` | README, Manager Guide, and Technical Design Markdown/HTML parity completed. |
| Task 3 — Supporting references | `0706292`, `6e2f49a`, `49acc6c`, `e5ed40b` | ADM specification, presentation, release notes, and evidence-gate wording completed. |
| Task 4 — Optionalization and runtime verification | `6380f1b`, `0859fce` | Apps Script moved to optional examples; the execution plan was captured; runtime verification completed. |
| Final verification | — | `198/198` tests passed; Node syntax passed; release-manifest tests passed; all 6 HTML files parsed; source/runtime SKILL SHA-256 matched; the working tree was clean; commits were not pushed. |

## File Responsibility Map

| File | Responsibility in this change |
|---|---|
| `plugins/avaya-case-review/skills/case-review/SKILL.md` | Canonical generation order, section ownership, ADM integration, output template, and reflection rules |
| `tests/test_case_review_contract.py` | Static regression enforcement for summary shape, technical-depth boundary, ADM behavior, documentation parity, and presentation parity |
| `tests/case_review_scenarios.json` | Behavioral cases for layered disclosure, deduplication, and ADM expansion |
| `README.md`, `README.html` | Short public statement of the layered report contract |
| `docs/MANAGER_ONBOARDING_GUIDE.md`, `.html` | Manager-facing explanation of what each section contains |
| `docs/TECHNICAL_DESIGN_DOCUMENT.md`, `.html` | Technical generation flow, section ownership, and evidence behavior |
| `docs/superpowers/specs/2026-08-02-adm-adaptive-integration-design.md` | Align the earlier ADM specification with the approved placement boundary |
| `docs/PRESENTATION.html` | Replace the obsolete Risk Flags/Recommendations slide with the current five-part report structure |
| `docs/RELEASE_NOTES.md`, `.html` | Record the layered-disclosure redesign under Unreleased |
| `%USERPROFILE%\.gemini\config\plugins\avaya-case-review\skills\case-review\SKILL.md` | Deployed runtime copy; synchronize only after repository validation passes |

---

### Task 1: Lock the Layered Report Contract and Update the Canonical SKILL

**Files:**
- Modify: `tests/test_case_review_contract.py:25-32,128-146,286-309`
- Modify: `tests/case_review_scenarios.json:38-43`
- Modify: `plugins/avaya-case-review/skills/case-review/SKILL.md:150-183,188-260,271-276`

- [x] **Step 1: Add a section extraction helper and failing contract tests**

Add this helper after `extract_report_template` in `tests/test_case_review_contract.py`:

```python
def extract_template_section(template: str, heading: str, next_heading: str) -> str:
    start = template.index(heading) + len(heading)
    end = template.index(next_heading, start)
    return template[start:end].strip()
```

Replace `test_executive_summary_replaces_verdict` and add the technical/ADM boundary tests:

```python
def test_executive_summary_is_one_layered_paragraph(self):
    template = extract_report_template(self.skill)
    summary = extract_template_section(
        template,
        "## Executive Summary",
        "## Technical & Incident Assessment",
    )

    self.assertNotIn("## Verdict", template)
    self.assertNotIn("###", summary)
    for removed in [
        "Core Incident Details",
        "Impact and Response",
        "Next Steps",
        "Future prevention",
    ]:
        self.assertNotIn(removed, summary)

    for required in [
        "one natural-language paragraph of 6-8 sentences",
        "one-sentence technical conclusion",
        "lowercase `unknown`",
        "conclusion-level information",
    ]:
        self.assertIn(required, self.skill)


def test_technical_assessment_adds_reasoning_without_restatement(self):
    template = extract_report_template(self.skill)
    technical = extract_template_section(
        template,
        "## Technical & Incident Assessment",
        "## Progress Summary",
    )

    self.assertIn("Start with problem clarification", technical)
    for required in [
        "environment or affected-component detail",
        "causal reasoning or an RCA-state explanation",
        "solution, workaround, implementation, or verification detail",
        "only paraphrases an Executive Summary sentence",
        "Existing prevention controls",
        "evidence confirms implementation",
        "Planned or committed preventive work",
    ]:
        self.assertIn(required, self.skill)


def test_adm_expands_technical_depth_without_duplicate_sections(self):
    template = extract_report_template(self.skill)
    for required in [
        "ADM mode activates",
        "Details/Findings",
        "Problem Clarification",
        "Cause",
        "Solution",
        "increases the depth of `Technical & Incident Assessment` only",
    ]:
        self.assertIn(required, self.skill)

    for forbidden in [
        "## Details/Findings",
        "## Problem Clarification",
        "## Cause",
        "## Solution",
    ]:
        self.assertNotIn(forbidden, template)
```

- [x] **Step 2: Update the scenario matrix for the approved behavior**

Replace `executive_summary_fields` and add two new objects in `tests/case_review_scenarios.json`:

```json
{
  "id": "executive_summary_layering",
  "input": "A mixed VP and technical-manager audience needs a concise incident overview without repeating the technical assessment.",
  "expected": "Render one natural-language Executive Summary paragraph of 6-8 sentences with conclusion-level facts only; exclude future prevention and detailed diagnostics.",
  "contract_markers": ["one natural-language paragraph of 6-8 sentences", "conclusion-level information", "Future prevention"]
},
{
  "id": "executive_technical_deduplication",
  "input": "The summary and technical assessment draw from the same findings, RCA state, mitigation, and outcome.",
  "expected": "State the headline conclusion once in Executive Summary and use Technical & Incident Assessment only to add mechanism, evidence interpretation, validation, or unresolved gaps.",
  "contract_markers": ["only paraphrases an Executive Summary sentence", "environment or affected-component detail", "solution, workaround, implementation, or verification detail"]
},
{
  "id": "adm_technical_depth_without_duplicate_sections",
  "input": "The user explicitly requests ADM for a case review.",
  "expected": "Increase Technical & Incident Assessment depth across all four ADM dimensions without appending a second four-heading report or expanding Executive Summary.",
  "contract_markers": ["ADM mode activates", "increases the depth of `Technical & Incident Assessment` only", "not required to display four mechanical ADM headings"]
}
```

Update the `required` scenario-ID set in `test_regression_matrix_covers_required_scenarios`:

```python
required = {
    "closed_resolved_old_record",
    "single_issue_with_evidence",
    "multi_problem_case",
    "gmail_no_results",
    "status_pings_only",
    "chronological_output_order",
    "executive_summary_layering",
    "executive_technical_deduplication",
    "adm_technical_depth_without_duplicate_sections",
    "lab_success_not_production_confirmed",
    "required_tool_missing",
    "conflicting_sources",
    "zero_case_evidence",
    "appendix_reverse_mapping",
}
```

- [x] **Step 3: Run the focused tests and verify the old contract fails**

Run:

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m unittest `
  tests.test_case_review_contract.CaseReviewContractTests.test_executive_summary_is_one_layered_paragraph `
  tests.test_case_review_contract.CaseReviewContractTests.test_technical_assessment_adds_reasoning_without_restatement `
  tests.test_case_review_contract.CaseReviewContractTests.test_adm_expands_technical_depth_without_duplicate_sections `
  tests.test_case_review_contract.CaseReviewContractTests.test_regression_matrix_covers_required_scenarios -v
```

Expected: FAIL because the current template still has three Executive Summary subheadings, contains `Future prevention`, and lacks canonical ADM/deduplication rules.

- [x] **Step 4: Replace the overlapping SKILL rules with the layered-disclosure contract**

Replace `### Executive Summary content` through the line before `### Step 5 - Enforce the Evidence Gate` with:

```markdown
### Layered Executive and Technical Content

`Executive Summary` owns conclusion-level information. `Technical & Incident Assessment` owns technical explanation. The Executive Summary states the conclusion; the technical assessment explains why that conclusion is justified.

#### Executive Summary contract

- Render one natural-language paragraph of 6-8 sentences with no internal subheadings.
- Cover, in order: event/date/time/location; affected scope; business impact; key response and outcome; one-sentence technical conclusion with RCA state; mitigation maturity and confirmed production outcome; current status; and the next evidence-backed checkpoint, owner, and ETA when stated.
- Use lowercase `unknown` for unsupported required facts.
- Do not include raw logs, detailed troubleshooting, configuration parameters, extended cause analysis, or Future prevention.

#### Technical & Incident Assessment contract

Start with problem clarification rather than another incident summary. Each paragraph must add at least one of:

- environment or affected-component detail;
- a technical finding or interpreted log excerpt;
- causal reasoning or an RCA-state explanation;
- a ruled-out path, unresolved hypothesis, or missing validation;
- solution, workaround, implementation, or verification detail;
- Existing prevention controls whose implementation is confirmed by evidence.

If a paragraph only paraphrases an Executive Summary sentence without adding one of those elements, remove it during reflection. Future prevention is excluded from Executive Summary; report Existing prevention controls only inside the relevant technical problem when evidence confirms implementation. Planned or committed preventive work that is not implemented remains planned or committed work or the next evidence-stated checkpoint; never label it an Existing prevention control or an agent recommendation. Omit controls when absent.

#### Adaptive ADM depth

ADM mode activates only when the user explicitly requests `ADM` or `Avaya Diagnostic Methodology`, case-insensitively. It increases the depth of `Technical & Incident Assessment` only and does not change Executive Summary length or append a second report.

- **Details/Findings:** environment, context, symptoms, relevant logs, and discovered facts.
- **Problem Clarification:** the actual core technical problem, separated from secondary symptoms and business impact.
- **Cause:** mechanism, evidence, ruled-out paths, suspected cause, missing evidence, and investigation state.
- **Solution:** fix, workaround, completed action, validation result, mitigation maturity, and next evidence-stated technical step.

Cover all four dimensions when evidence permits. Their content may use natural paragraphs, short lists, or contextual subheadings; the report is not required to display four mechanical ADM headings.

#### Generation order

1. Complete the evidence ledger, source-conflict analysis, RCA state, mitigation maturity, and single-versus-multi-problem classification.
2. Draft `Technical & Incident Assessment` from the evidence ledger.
3. Extract conclusion-level facts from the technical assessment and evidence ledger into Executive Summary.
4. Remove technical paragraphs that merely restate the summary and remove summary details that belong only in technical analysis.
```

Replace the two template sections with:

```markdown
## Executive Summary
<One natural-language paragraph of 6-8 sentences covering event/date/time/location, affected scope, business impact, key response and outcome, one-sentence technical conclusion with RCA state, mitigation maturity and production outcome, current status, and next evidence-backed checkpoint/owner/ETA. Use lowercase unknown for unsupported required facts. Exclude prevention content and detailed technical reasoning.>

## Technical & Incident Assessment
<Start with problem clarification. Add environment/findings, cause reasoning, solution/validation, and unresolved technical gaps. Do not restate the complete event, business impact, or management status.>
```

Replace the conditional-structure rules after the template with:

```markdown
For the conditional technical section:

- **Multi-problem:** use `Problem Statement`, then `Problem 1 - <Record ID>`, `Problem 2 - <Record ID>`, and cover problem clarification, findings, cause, solution/validation, mitigation maturity, and unresolved gaps for each problem.
- **Single issue:** use `Incident & RCA Summary` and cover problem clarification, findings, cause, solution/validation, mitigation maturity, and unresolved gaps.
- Report Existing prevention controls under the relevant technical problem only when case evidence confirms implementation. Describe unimplemented planned or committed preventive work only as planned or committed work or an evidence-stated next checkpoint; never label it an Existing prevention control or recommendation.

Do not render both conditional structures. Do not create a standalone telemetry section or a second ADM block.
```

Add these reflection checks after the current chronological-order check:

```markdown
11. Confirm Executive Summary is one 6-8 sentence paragraph with no internal subheadings or Future prevention.
12. Confirm its root-cause conclusion is at most one sentence and detailed causal reasoning appears only in Technical & Incident Assessment.
13. Remove any technical paragraph that merely paraphrases the summary without adding findings, mechanism, validation, or unresolved gaps.
14. When ADM is requested, confirm all four ADM dimensions are covered inside Technical & Incident Assessment without adding a second ADM outline.
```

Replace the final prevention-related non-negotiable rules with:

```markdown
- The report must not generate risk lists, risk scores, manager directives, or unsupported recommendations.
- Future prevention is excluded from Executive Summary. Existing prevention controls may appear only under the relevant technical problem and only when evidence confirms implementation. Planned or committed preventive work remains planned or committed work or an evidence-stated checkpoint; it is never labeled an Existing prevention control or recommendation.
- Executive Summary states conclusion-level information; Technical & Incident Assessment adds explanation and proof without repeating the summary narrative.
- The manager should understand the incident, impact, current technical conclusion, mitigation, status, and next checkpoint from Executive Summary without reading the technical detail first.
```

- [x] **Step 5: Run focused tests and verify they pass**

Run the command from Step 3 again.

Expected: all four focused tests PASS.

- [x] **Step 6: Commit the canonical contract and tests**

```powershell
git add -- plugins/avaya-case-review/skills/case-review/SKILL.md tests/test_case_review_contract.py tests/case_review_scenarios.json
git diff --cached --check
git diff --cached --stat
git commit -m "feat(case-review): separate executive and technical content"
```

Expected: one commit containing only the canonical skill and contract-test files.

---

### Task 2: Align README, Manager Guide, and Technical Design Documentation

**Files:**
- Modify: `tests/test_case_review_contract.py:181-202`
- Modify: `README.md:9-18`
- Modify: `README.html:109-118`
- Modify: `docs/MANAGER_ONBOARDING_GUIDE.md:99-114`
- Modify: `docs/MANAGER_ONBOARDING_GUIDE.html:119-136`
- Modify: `docs/TECHNICAL_DESIGN_DOCUMENT.md:127-147`
- Modify: `docs/TECHNICAL_DESIGN_DOCUMENT.html:299-325`

- [x] **Step 1: Add a failing documentation-parity test**

Add this test after `test_current_contract_docs_match_skill`:

```python
def test_contract_docs_describe_layered_disclosure(self):
    required = [
        "6-8 sentence",
        "conclusion-level",
        "technical reasoning",
        "Future prevention is excluded from Executive Summary",
        "Existing prevention controls",
        "evidence confirms they are implemented",
        "Planned or committed preventive work",
        "never labeled an Existing prevention control or an agent recommendation",
    ]
    for name, content in self.contract_docs.items():
        with self.subTest(document=name):
            for marker in required:
                self.assertIn(marker, content)
            self.assertNotIn(
                "Executive Summary covering the incident, timing and location, affected scope, business effect, response, root cause, prevention priorities",
                content,
            )
```

- [x] **Step 2: Run the documentation test and verify it fails**

Run:

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m unittest tests.test_case_review_contract.CaseReviewContractTests.test_contract_docs_describe_layered_disclosure -v
```

Expected: FAIL because the current documents still describe field-by-field prevention content in Executive Summary.

- [x] **Step 3: Update README Markdown and HTML with the public boundary**

Use this exact contract language in both README variants, with HTML tags substituted in `README.html`:

```markdown
- The report starts with one **6-8 sentence Executive Summary** paragraph for management and technical readers. It contains conclusion-level incident, impact, response, RCA-state, mitigation, status, and next-checkpoint information.
- **Technical & Incident Assessment** supplies the technical reasoning: environment, findings, causal mechanism, validation, and unresolved gaps without restating the summary.
- Future prevention is excluded from Executive Summary. Existing prevention controls appear only in the technical assessment when case evidence confirms they are implemented. Planned or committed preventive work remains planned work or an evidence-stated next checkpoint; it is never labeled an Existing prevention control or an agent recommendation.
```

HTML equivalent:

```html
<li>The report starts with one <strong>6-8 sentence Executive Summary</strong> paragraph for management and technical readers. It contains conclusion-level incident, impact, response, RCA-state, mitigation, status, and next-checkpoint information.</li>
<li><strong>Technical &amp; Incident Assessment</strong> supplies the technical reasoning: environment, findings, causal mechanism, validation, and unresolved gaps without restating the summary.</li>
<li>Future prevention is excluded from Executive Summary. Existing prevention controls appear only in the technical assessment when case evidence confirms they are implemented. Planned or committed preventive work remains planned work or an evidence-stated next checkpoint; it is never labeled an Existing prevention control or an agent recommendation.</li>
```

- [x] **Step 4: Update Manager Onboarding Markdown and HTML**

Replace only the Executive Summary and Technical Assessment list items with the following; leave the intervening Two Freshness Clocks item unchanged:

```markdown
1. **Executive Summary**: One citation-free, 6-8 sentence paragraph for management and technical readers. It contains conclusion-level incident, timing/location, affected scope, business impact, key response, one-sentence RCA state/conclusion, mitigation and production outcome, current status, and the next evidence-backed checkpoint. Unsupported required facts are `unknown`.
3. **Conditional Technical & Incident Assessment**: Starts with problem clarification and adds technical reasoning through environment, findings, cause analysis, solution/validation, and unresolved gaps. It does not restate the complete incident or business impact. Future prevention is excluded from Executive Summary. Existing prevention controls appear here only when evidence confirms they are implemented. Planned or committed preventive work remains planned work or an evidence-stated next checkpoint; it is never labeled an Existing prevention control or an agent recommendation.
```

Use these exact HTML list items in the companion:

```html
<li><strong>Executive Summary</strong>: One citation-free, 6-8 sentence paragraph for management and technical readers. It contains conclusion-level incident, timing/location, affected scope, business impact, key response, one-sentence RCA state/conclusion, mitigation and production outcome, current status, and the next evidence-backed checkpoint. Unsupported required facts are <code>unknown</code>.</li>
<li><strong>Conditional Technical &amp; Incident Assessment</strong>: Starts with problem clarification and adds technical reasoning through environment, findings, cause analysis, solution/validation, and unresolved gaps. It does not restate the complete incident or business impact. Future prevention is excluded from Executive Summary. Existing prevention controls appear here only when evidence confirms they are implemented. Planned or committed preventive work remains planned work or an evidence-stated next checkpoint; it is never labeled an Existing prevention control or an agent recommendation.</li>
```

- [x] **Step 5: Update Technical Design Markdown and HTML**

Replace the output-schema items for Executive Summary and Conditional Technical Assessment with:

```markdown
1. **Executive Summary & Status**: One citation-free, 6-8 sentence paragraph containing conclusion-level incident, affected scope, business impact, key response, one-sentence RCA state/conclusion, mitigation and production outcome, current status, and the next evidenced checkpoint.
3. **Conditional Technical Assessment**: Starts with problem clarification and adds technical reasoning through environment/findings, causal mechanism, solution/validation, and unresolved gaps. Exactly one multi-problem `Problem Statement` or single-issue `Incident & RCA Summary` is rendered.
```

Add these evidence-processing rules:

```markdown
9. Generate Technical & Incident Assessment before extracting Executive Summary so the headline conclusion has one reasoning source.
10. Remove technical paragraphs that only paraphrase the summary without adding findings, mechanism, validation, or unresolved gaps.
11. Future prevention is excluded from Executive Summary. Existing prevention controls appear only under the relevant technical problem when evidence confirms they are implemented. Planned or committed preventive work remains planned work or an evidence-stated next checkpoint; it is never labeled an Existing prevention control or an agent recommendation.
```

Use these exact HTML elements in the companion:

```html
<li><strong>Executive Summary &amp; Status</strong>: One citation-free, 6-8 sentence paragraph containing conclusion-level incident, affected scope, business impact, key response, one-sentence RCA state/conclusion, mitigation and production outcome, current status, and the next evidenced checkpoint.</li>
<li><strong>Conditional Technical Assessment</strong>: Starts with problem clarification and adds technical reasoning through environment/findings, causal mechanism, solution/validation, and unresolved gaps. Exactly one multi-problem <code>Problem Statement</code> or single-issue <code>Incident &amp; RCA Summary</code> is rendered.</li>
<li>Generate Technical &amp; Incident Assessment before extracting Executive Summary so the headline conclusion has one reasoning source.</li>
<li>Remove technical paragraphs that only paraphrase the summary without adding findings, mechanism, validation, or unresolved gaps.</li>
<li>Future prevention is excluded from Executive Summary. Existing prevention controls appear only under the relevant technical problem when evidence confirms they are implemented. Planned or committed preventive work remains planned work or an evidence-stated next checkpoint; it is never labeled an Existing prevention control or an agent recommendation.</li>
```

- [x] **Step 6: Run documentation and portability tests**

Run:

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m unittest `
  tests.test_case_review_contract.CaseReviewContractTests.test_contract_docs_describe_layered_disclosure `
  tests.test_case_review_contract.CaseReviewContractTests.test_current_contract_docs_match_skill `
  tests.test_case_review_contract.CaseReviewContractTests.test_readme_files_are_english_only `
  tests.test_case_review_contract.CaseReviewContractTests.test_distributable_docs_have_no_machine_specific_file_urls -v
```

Expected: all four tests PASS.

- [x] **Step 7: Commit synchronized core documentation**

```powershell
git add -- README.md README.html docs/MANAGER_ONBOARDING_GUIDE.md docs/MANAGER_ONBOARDING_GUIDE.html docs/TECHNICAL_DESIGN_DOCUMENT.md docs/TECHNICAL_DESIGN_DOCUMENT.html tests/test_case_review_contract.py
git diff --cached --check
git diff --cached --stat
git commit -m "docs(case-review): align layered report contract"
```

Expected: one commit containing the core Markdown/HTML parity updates and their regression test.

---

### Task 3: Align ADM, Presentation, and Release Notes

**Files:**
- Modify: `tests/test_case_review_contract.py:7-21,238-252`
- Modify: `docs/superpowers/specs/2026-08-02-adm-adaptive-integration-design.md:1-19,59-74,134-142`
- Modify: `docs/PRESENTATION.html:485-515`
- Modify: `docs/RELEASE_NOTES.md:7-12`
- Modify: `docs/RELEASE_NOTES.html:114-118`

- [x] **Step 1: Add failing regression coverage for the ADM specification and presentation**

Add constants:

```python
ADM_SPEC = ROOT / "docs/superpowers/specs/2026-08-02-adm-adaptive-integration-design.md"
PRESENTATION_HTML = ROOT / "docs/PRESENTATION.html"
```

Add this test:

```python
def test_adm_spec_and_presentation_follow_layered_contract(self):
    adm = read(ADM_SPEC)
    presentation = read(PRESENTATION_HTML)
    release_docs = [read(RELEASE_MD), read(RELEASE_HTML)]

    for marker in [
        "Executive Summary remains one 6-8 sentence paragraph",
        "Future prevention is excluded from Executive Summary",
        "Existing prevention controls require evidence confirming implementation",
        "Planned or committed preventive work remains an evidence-stated checkpoint or planned work, not a recommendation or an implemented control",
        "does not append another set of ADM sections",
    ]:
        self.assertIn(marker, adm)

    for marker in [
        "6-8 Sentence Executive Summary",
        "Technical &amp; Incident Assessment",
        "Evidence Appendix",
    ]:
        self.assertIn(marker, presentation)

    for obsolete in [
        "Risk Flags & Sanity Audit",
        "Recommended Manager Actions",
        "prevention priorities",
    ]:
        self.assertNotIn(obsolete, presentation)

    for release in release_docs:
        self.assertIn("layered disclosure", release.lower())
        self.assertIn("6-8 sentence Executive Summary", release)
```

- [x] **Step 2: Run the new regression and verify it fails**

Run:

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m unittest tests.test_case_review_contract.CaseReviewContractTests.test_adm_spec_and_presentation_follow_layered_contract -v
```

Expected: FAIL because the earlier ADM spec still assigns prevention to Executive Summary and the presentation still shows obsolete Risk Flags and Recommended Manager Actions cards.

- [x] **Step 3: Align the earlier ADM specification**

Add this note after its status:

```markdown
> Executive-versus-technical placement is refined by `2026-08-04-executive-technical-dedup-design.md`. The newer placement rules control if wording differs.
```

Replace the Case Review placement bullets with:

```markdown
- **Executive Summary:** Executive Summary remains one 6-8 sentence paragraph containing conclusion-level incident, impact, response, one-sentence RCA state/conclusion, mitigation, status, and next-checkpoint information. Future prevention is excluded from Executive Summary.
- **Technical & Incident Assessment:** open with Problem Clarification; integrate Details/Findings; express Cause through RCA state and reasoning; express Solution through mitigation and validation; include Existing prevention controls only when evidence confirms implementation.
- **Preventive work boundary:** Planned or committed preventive work remains an evidence-stated checkpoint or planned work, not a recommendation or an implemented control.
- **ADM rendering:** deeper ADM content stays inside Technical & Incident Assessment and does not append another set of ADM sections or enlarge Executive Summary.
```

Replace `No ADM request: use the standard v1.5.0 output` with:

```markdown
- **No ADM request:** use the current layered report contract with standard technical depth.
```

- [x] **Step 4: Replace the obsolete presentation cards**

Use this five-card block in `docs/PRESENTATION.html`:

```html
<div class="card" style="padding: 12px 20px;">
    <h3>1. 6-8 Sentence Executive Summary</h3>
    <p style="margin: 0;">One paragraph covering conclusion-level incident, impact, response, RCA state, mitigation, status, and next checkpoint.</p>
</div>
<div class="card" style="padding: 12px 20px;">
    <h3>2. Technical &amp; Incident Assessment</h3>
    <p style="margin: 0;">Problem clarification, findings, cause reasoning, solution validation, and unresolved technical gaps without repeating the summary.</p>
</div>
<div class="card" style="padding: 12px 20px;">
    <h3>3. Progress Summary &amp; Timeline</h3>
    <p style="margin: 0;">Substantive milestones from the case record, Gmail, supplied documents, and logs, ordered oldest to newest.</p>
</div>
<div class="card" style="padding: 12px 20px;">
    <h3>4. Ownership &amp; Next Step</h3>
    <p style="margin: 0;">Evidence-stated assignee, last concrete action, next action, owner, and due date.</p>
</div>
<div class="card" style="padding: 12px 20px;">
    <h3>5. Evidence Appendix</h3>
    <p style="margin: 0;">Final reverse-mapped evidence table preserving the audit chain without inline citations.</p>
</div>
```

- [x] **Step 5: Record the redesign under Unreleased**

Append these Markdown bullets under `[Unreleased]`:

```markdown
* Applies layered disclosure: a one-paragraph, 6-8 sentence Executive Summary states conclusion-level information while Technical & Incident Assessment supplies technical reasoning and validation.
* Removes Future prevention from Executive Summary; evidence-confirmed Existing prevention controls remain in the relevant technical problem only, while planned or committed preventive work remains an evidence-stated checkpoint or planned work, not a recommendation or implemented control.
* Keeps ADM depth inside Technical & Incident Assessment instead of appending a duplicate ADM outline.
```

Add an equivalent paragraph to the HTML Unreleased block:

```html
<p>Applies layered disclosure: a one-paragraph, 6-8 sentence Executive Summary states conclusion-level information while Technical &amp; Incident Assessment supplies technical reasoning and validation. Future prevention is excluded from Executive Summary; evidence-confirmed Existing prevention controls remain in the relevant technical problem only, while planned or committed preventive work remains an evidence-stated checkpoint or planned work, not a recommendation or implemented control. ADM depth stays inside Technical &amp; Incident Assessment instead of appending a duplicate ADM outline.</p>
```

- [x] **Step 6: Run focused presentation, release, and ADM checks**

Run:

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m unittest `
  tests.test_case_review_contract.CaseReviewContractTests.test_adm_spec_and_presentation_follow_layered_contract `
  tests.test_case_review_contract.CaseReviewContractTests.test_release_metadata_targets_v1_6_0 `
  tests.test_case_review_contract.CaseReviewContractTests.test_distributable_docs_have_no_machine_specific_file_urls -v
```

Expected: all three tests PASS.

- [x] **Step 7: Commit the supporting documentation**

```powershell
git add -- docs/superpowers/specs/2026-08-02-adm-adaptive-integration-design.md docs/PRESENTATION.html docs/RELEASE_NOTES.md docs/RELEASE_NOTES.html tests/test_case_review_contract.py
git diff --cached --check
git diff --cached --stat
git commit -m "docs(case-review): refresh layered report references"
```

Expected: one documentation commit with its regression test.

---

### Task 4: Synchronize the Runtime Skill and Perform Full Verification

**Files:**
- Source: `plugins/avaya-case-review/skills/case-review/SKILL.md`
- Deploy: `%USERPROFILE%\.gemini\config\plugins\avaya-case-review\skills\case-review\SKILL.md`
- Verify: `examples/optional-appsscript/Code.gs`
- Verify: `release-manifest.txt`

- [x] **Step 1: Confirm the repository contract is clean before deployment**

Run:

```powershell
$forbiddenFallback = [string]::Concat([char]0x4E0D, [char]0x77E5, [char]0x9053)
rg -n -F $forbiddenFallback . --glob '!*.zip' --glob '!*.pyc'
git diff --check
```

Expected: `rg` returns no matches and `git diff --check` reports no errors.

- [x] **Step 2: Run the complete automated suite**

Run:

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m unittest discover -s tests -p 'test_*.py' -v
```

Expected: all tests PASS; with the post-review coverage, the suite reports at least 198 tests.

- [x] **Step 3: Validate the optional Apps Script and release manifest**

Run:

```powershell
Get-Content -Raw examples/optional-appsscript/Code.gs | node --check
python -m unittest tests.test_release_manifest -v
```

Expected: JavaScript syntax check exits 0 and all release-manifest tests PASS. The optional Apps Script remains outside the active release manifest.

- [x] **Step 4: Copy the validated canonical SKILL to the deployed runtime**

Run:

```powershell
$sourceSkill = Join-Path (Get-Location) 'plugins\avaya-case-review\skills\case-review\SKILL.md'
$runtimeSkill = Join-Path $env:USERPROFILE '.gemini\config\plugins\avaya-case-review\skills\case-review\SKILL.md'
if (-not (Test-Path -LiteralPath $runtimeSkill)) {
    throw "Runtime SKILL not found: $runtimeSkill"
}
Copy-Item -LiteralPath $sourceSkill -Destination $runtimeSkill -Force
```

Expected: the runtime skill is replaced without running the installer or restarting the Gmail broker.

- [x] **Step 5: Prove source and runtime copies are identical**

Run:

```powershell
$sourceSkill = Join-Path (Get-Location) 'plugins\avaya-case-review\skills\case-review\SKILL.md'
$runtimeSkill = Join-Path $env:USERPROFILE '.gemini\config\plugins\avaya-case-review\skills\case-review\SKILL.md'
$sourceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $sourceSkill).Hash
$runtimeHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $runtimeSkill).Hash
if ($sourceHash -ne $runtimeHash) {
    throw "Runtime SKILL hash does not match repository source"
}
$forbiddenFallback = [string]::Concat([char]0x4E0D, [char]0x77E5, [char]0x9053)
rg -n -F $forbiddenFallback $runtimeSkill
```

Expected: hashes match and `rg` returns no matches.

- [x] **Step 6: Inspect the final repository state**

Run:

```powershell
git log -4 --oneline
git status --short
git diff --check
```

Expected: the Task 1-4 execution-record commits listed above are visible; the working tree is clean; no whitespace errors are reported.

---

## Completion Criteria

- Executive Summary is one natural-language paragraph of 6-8 sentences.
- Future prevention is absent from Executive Summary.
- Technical & Incident Assessment starts with problem clarification and adds reasoning, findings, validation, or unresolved gaps rather than paraphrasing the summary.
- ADM expands only Technical & Incident Assessment and never appends a second rigid ADM outline.
- Existing prevention controls appear only under a relevant technical problem and only when evidence confirms implementation. Planned or committed preventive work remains planned work or an evidence-stated checkpoint and is never labeled an Existing prevention control or recommendation.
- Markdown, HTML, presentation, release notes, scenarios, tests, and deployed runtime skill describe the same contract.
- The complete test suite, JavaScript syntax check, release-manifest checks, and `git diff --check` all pass.
