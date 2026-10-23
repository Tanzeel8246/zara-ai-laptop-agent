"""Phase 6 release-consistency checks.

The product page and the doc set are deliverables too: the page must
exist as a single self-contained file (no external assets), and every
local file the README links to must exist in the tree.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_product_page_exists_and_is_self_contained():
    page = ROOT / "website" / "index.html"
    assert page.is_file()
    html = page.read_text(encoding="utf-8")
    # Identity colours from the tray icon must be the page's palette.
    assert "#0A1F3A" in html and "#3DE6A8" in html
    # Zero external assets: no external stylesheets/scripts/images/fonts.
    assert not re.search(r'<link[^>]+href="https?://', html)
    assert not re.search(r'<script[^>]+src=', html)
    assert not re.search(r'<img[^>]+src=', html)
    assert "@import" not in html
    # No imagery of people at all on the product page.
    assert "<img" not in html


def test_readme_links_resolve():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    targets = re.findall(r"\]\(([^)]+)\)", readme)
    local = [t for t in targets if not t.startswith(("http://", "https://", "#", "mailto:"))]
    assert local, "README should link to the docs"
    missing = [t for t in local if not (ROOT / t.split("#")[0]).exists()]
    assert not missing, f"README links to missing files: {missing}"


def test_doc_set_complete():
    for name in (
        "USER_GUIDE.md",
        "SELLER_GUIDE.md",
        "EULA.md",
        "PRIVACY.md",
        "WHATSAPP_DISCLAIMER.md",
        "SECURITY.md",
        "CHANGELOG.md",
    ):
        assert (ROOT / "docs" / name).is_file(), name
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "MindCrafts AI" in license_text and "MIT" not in license_text
