import re
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
DECK = ROOT / "docs/Avaya_Case_Review_Suite_Presentation.pptx"
DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"


def slide_texts(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        slide_names = sorted(
            (
                name
                for name in archive.namelist()
                if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
            ),
            key=lambda name: int(re.search(r"\d+", Path(name).stem).group()),
        )
        return [
            "\n".join(
                node.text or ""
                for node in ElementTree.fromstring(archive.read(name)).iter(
                    f"{{{DRAWING_NS}}}t"
                )
            )
            for name in slide_names
        ]


class PresentationPptxContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.slides = slide_texts(DECK)
        cls.deck_text = "\n".join(cls.slides)

    def test_required_current_contract_and_architecture_language(self):
        required = (
            "6-8 Sentence Executive Summary",
            "Technical & Incident Assessment",
            "Progress Summary",
            "Ownership & Next Step",
            "Timeline",
            "Appendix A",
            "Evidence Register",
            "Single Managed Edge Broker",
            "edge_broker_profile",
            "Conditional Managed Edge Sign-In",
            "Evidence-confirmed",
            "reference destination",
            "Faster Preparation",
            "Evidence Traceability",
            "Earlier Escalation Signals",
        )
        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.deck_text)

    def test_stale_or_unsupported_claims_are_absent(self):
        prohibited = (
            "Verdict",
            "Risk Flag",
            "Recommended Manager Actions",
            "Sanity & Risk Auditor",
            "2-4 concrete",
            "Zero Technical Blind Spots",
            "Zero Blind Spots",
            "80% Time Saved",
            "30% Faster MTTR",
            "chrome_profile",
            "One-Time Google SSO",
            "Chrome window opens",
            "Flagged as MISDIRECTED ESCALATION",
            "Automatically verifies whether",
            "Enforces official Javadoc path",
            "blaming JTAPI SDK null returns instead of CM",
        )
        for phrase in prohibited:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase.casefold(), self.deck_text.casefold())

    def test_report_structure_uses_six_canonical_sections_in_order(self):
        candidates = [
            text
            for text in self.slides
            if "6-8 Sentence Executive Summary" in text
            and "Technical & Incident Assessment" in text
            and "Appendix A" in text
        ]
        self.assertEqual(
            len(candidates),
            1,
            "Expected exactly one report-structure slide",
        )
        report_slide = candidates[0]
        headings = (
            "6-8 Sentence Executive Summary",
            "Technical & Incident Assessment",
            "Progress Summary",
            "Ownership & Next Step",
            "Timeline",
            "Appendix A",
        )
        positions = [report_slide.index(heading) for heading in headings]
        self.assertEqual(positions, sorted(positions))
        self.assertNotEqual(
            report_slide.index("Progress Summary"),
            report_slide.index("Timeline"),
        )
        self.assertIn("Evidence Register", report_slide)


if __name__ == "__main__":
    unittest.main()
