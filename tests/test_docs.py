"""Keep the documentation honest: links resolve, demo art is well-formed."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")

DOCS = ["README.md", "README.tr.md", "CONTRIBUTING.md", "CHANGELOG.md"]


@pytest.mark.parametrize("document", DOCS)
def test_document_exists(document):
    assert (REPO / document).is_file()


@pytest.mark.parametrize("document", DOCS)
def test_relative_links_resolve(document):
    text = (REPO / document).read_text(encoding="utf-8")
    broken = []
    for target in LINK_RE.findall(text):
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        path = (REPO / target.split("#")[0].strip()).resolve()
        if not path.exists():
            broken.append(target)
    assert broken == [], f"broken links in {document}: {broken}"


@pytest.mark.parametrize("image", ["docs/demo.svg", "docs/demo-delete.svg", "docs/demo-undo.svg"])
def test_demo_svg_is_valid_xml(image):
    tree = ET.parse(REPO / image)
    root = tree.getroot()
    assert root.tag.endswith("svg")
    assert root.get("width") and root.get("height")
    # the screenshots always show a title bar with the three window dots
    circles = [el for el in root.iter() if el.tag.endswith("circle")]
    assert len(circles) == 3


def test_readme_documents_every_kind():
    from devdust import rules

    readme = (REPO / "README.md").read_text(encoding="utf-8")
    missing = [kind for kind in rules.kinds() if f"`{kind}`" not in readme]
    assert missing == [], f"kinds missing from the README table: {missing}"
