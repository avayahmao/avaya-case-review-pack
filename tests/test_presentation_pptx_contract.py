import posixpath
import re
import unittest
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
DECK = ROOT / "docs/Avaya_Case_Review_Suite_Presentation.pptx"
DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
PRESENTATION_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"a": DRAWING_NS, "p": PRESENTATION_NS}


@dataclass(frozen=True)
class TextShape:
    text: str
    x: int
    y: int
    cx: int
    cy: int
    shape_id: str = "fixture"


def slide_names(archive: zipfile.ZipFile) -> list[str]:
    return sorted(
        (
            name
            for name in archive.namelist()
            if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
        ),
        key=lambda name: int(re.search(r"\d+", Path(name).stem).group()),
    )


def slide_size(archive: zipfile.ZipFile) -> tuple[int, int]:
    root = ElementTree.fromstring(archive.read("ppt/presentation.xml"))
    size = root.find("p:sldSz", NS)
    if size is None:
        raise AssertionError("ppt/presentation.xml has no p:sldSz")
    return int(size.get("cx", "0")), int(size.get("cy", "0"))


def joined_shape_text(shape: ElementTree.Element) -> str:
    paragraphs = []
    for paragraph in shape.findall(".//a:p", NS):
        text = "".join(node.text or "" for node in paragraph.findall(".//a:t", NS))
        if text:
            paragraphs.append(text)
    return "\n".join(paragraphs)


def shape_geometry(shape: ElementTree.Element) -> tuple[int, int, int, int] | None:
    local_name = shape.tag.rsplit("}", 1)[-1]
    if local_name == "graphicFrame":
        transform = shape.find("p:xfrm", NS)
    else:
        transform = shape.find("p:spPr/a:xfrm", NS)
    if transform is None:
        return None
    offset = transform.find("a:off", NS)
    extent = transform.find("a:ext", NS)
    if offset is None or extent is None:
        return None
    return (
        int(offset.get("x", "0")),
        int(offset.get("y", "0")),
        int(extent.get("cx", "0")),
        int(extent.get("cy", "0")),
    )


def text_shapes(root: ElementTree.Element) -> list[TextShape]:
    shapes = []
    # Current deck text uses p:sp. Connector and graphic-frame support keeps the
    # reader correct if a future template puts text in either common container.
    containers = []
    for tag in ("sp", "cxnSp", "graphicFrame"):
        containers.extend(root.findall(f".//p:{tag}", NS))
    for index, shape in enumerate(containers, start=1):
        text = joined_shape_text(shape)
        geometry = shape_geometry(shape)
        if not text or geometry is None:
            continue
        metadata = shape.find(".//p:cNvPr", NS)
        identifier = metadata.get("id") if metadata is not None else str(index)
        shapes.append(TextShape(text, *geometry, shape_id=f"{index}:{identifier}"))
    return shapes


def shape_intersects_canvas(shape: TextShape, canvas: tuple[int, int]) -> bool:
    """Use a visible-intersection rule, allowing intentionally clipped shapes.

    A shape is visible only when both extents are positive and its rectangle has
    a positive-area intersection with the slide canvas. Fully off-canvas and
    zero-size shapes therefore cannot satisfy required contract markers.
    """

    width, height = canvas
    return (
        shape.cx > 0
        and shape.cy > 0
        and shape.x < width
        and shape.y < height
        and shape.x + shape.cx > 0
        and shape.y + shape.cy > 0
    )


def visible_marker_present(
    shapes: list[TextShape], marker: str, canvas: tuple[int, int]
) -> bool:
    return any(
        marker in shape.text and shape_intersects_canvas(shape, canvas)
        for shape in shapes
    )


def visual_reading_order(
    shapes: list[TextShape], slide_height: int
) -> list[TextShape]:
    """Order rows top-to-bottom, then shapes left-to-right within each row."""

    tolerance = max(1, slide_height // 100)
    remaining = sorted(shapes, key=lambda shape: (shape.y, shape.x))
    ordered = []
    while remaining:
        row_y = remaining[0].y
        row = [shape for shape in remaining if abs(shape.y - row_y) <= tolerance]
        row_ids = {id(shape) for shape in row}
        ordered.extend(sorted(row, key=lambda shape: shape.x))
        remaining = [shape for shape in remaining if id(shape) not in row_ids]
    return ordered


def deck_text_and_shapes(
    path: Path,
) -> tuple[tuple[int, int], list[str], list[list[TextShape]]]:
    with zipfile.ZipFile(path) as archive:
        canvas = slide_size(archive)
        raw_slides = []
        shape_slides = []
        for name in slide_names(archive):
            root = ElementTree.fromstring(archive.read(name))
            raw_slides.append(
                "\n".join(
                    node.text or "" for node in root.iter(f"{{{DRAWING_NS}}}t")
                )
            )
            shape_slides.append(text_shapes(root))
        return canvas, raw_slides, shape_slides


def relationship_part(source_part: str) -> str:
    folder, filename = posixpath.split(source_part)
    return posixpath.join(folder, "_rels", f"{filename}.rels")


def resolve_relationship_target(source_part: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(posixpath.dirname(source_part), target))


def relationship_targets(
    archive: zipfile.ZipFile, source_part: str, relationship_suffix: str
) -> list[str]:
    rels_name = relationship_part(source_part)
    if rels_name not in archive.namelist():
        return []
    root = ElementTree.fromstring(archive.read(rels_name))
    targets = []
    for relationship in root.findall(f"{{{PACKAGE_REL_NS}}}Relationship"):
        if relationship.get("Type", "").endswith(relationship_suffix):
            targets.append(
                resolve_relationship_target(source_part, relationship.get("Target", ""))
            )
    return targets


class PresentationPptxContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.canvas, cls.slides, cls.shape_slides = deck_text_and_shapes(DECK)
        cls.deck_text = "\n".join(cls.slides)
        cls.visible_deck_text = "\n".join(
            shape.text
            for shapes in cls.shape_slides
            for shape in shapes
            if shape_intersects_canvas(shape, cls.canvas)
        )

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
                self.assertIn(phrase, self.visible_deck_text)

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

    def test_slide_10_has_six_separate_sections_in_visual_reading_order(self):
        self.assertGreaterEqual(len(self.shape_slides), 10)
        report_shapes = [
            shape
            for shape in self.shape_slides[9]
            if shape_intersects_canvas(shape, self.canvas)
        ]
        headings = (
            "1. 6-8 Sentence Executive Summary",
            "2. Technical & Incident Assessment",
            "3. Progress Summary",
            "4. Ownership & Next Step",
            "5. Timeline",
            "6. Appendix A — Evidence Register",
        )
        heading_shapes = []
        for heading in headings:
            matches = [shape for shape in report_shapes if heading in shape.text]
            with self.subTest(heading=heading):
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0].text.count(heading), 1)
            heading_shapes.append(matches[0])
        self.assertEqual(len({shape.shape_id for shape in heading_shapes}), 6)
        visually_ordered = visual_reading_order(heading_shapes, self.canvas[1])
        self.assertEqual(
            [shape.shape_id for shape in visually_ordered],
            [shape.shape_id for shape in heading_shapes],
        )

    def test_template_hierarchy_is_preserved(self):
        with zipfile.ZipFile(DECK) as archive:
            names = set(archive.namelist())
            masters = sorted(
                name
                for name in names
                if re.fullmatch(r"ppt/slideMasters/slideMaster\d+\.xml", name)
            )
            layouts = sorted(
                name
                for name in names
                if re.fullmatch(r"ppt/slideLayouts/slideLayout\d+\.xml", name)
            )
            themes = sorted(
                name
                for name in names
                if re.fullmatch(r"ppt/theme/theme\d+\.xml", name)
            )
            self.assertEqual(len(masters), 1)
            self.assertEqual(len(layouts), 11)
            self.assertTrue(themes)
            for slide in slide_names(archive):
                targets = relationship_targets(archive, slide, "/slideLayout")
                with self.subTest(slide=slide):
                    self.assertEqual(len(targets), 1)
                    self.assertIn(targets[0], names)
            for layout in layouts:
                targets = relationship_targets(archive, layout, "/slideMaster")
                with self.subTest(layout=layout):
                    self.assertEqual(len(targets), 1)
                    self.assertIn(targets[0], names)
            for master in masters:
                targets = relationship_targets(archive, master, "/theme")
                with self.subTest(master=master):
                    self.assertEqual(len(targets), 1)
                    self.assertIn(targets[0], names)

    def test_visible_marker_helper_rejects_zero_size_and_off_canvas_text(self):
        marker = "Single Managed Edge Broker"
        shapes = [
            TextShape(marker, 10, 10, 0, 20),
            TextShape(marker, 110, 10, 20, 20),
            TextShape(marker, 10, 110, 20, 20),
        ]
        self.assertFalse(visible_marker_present(shapes, marker, (100, 100)))
        shapes.append(TextShape(marker, 90, 90, 20, 20))
        self.assertTrue(visible_marker_present(shapes, marker, (100, 100)))


if __name__ == "__main__":
    unittest.main()
