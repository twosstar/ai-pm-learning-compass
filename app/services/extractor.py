import re
from dataclasses import dataclass
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup


def clean_course_content(text: str) -> str:
    noise = re.compile(r"(?:results matching.*|no results matching.*|copyright\s*©?.*|all rights reserved.*)$", re.IGNORECASE)
    lines = []
    for line in text.splitlines():
        value = " ".join(line.split()).strip()
        if not value or noise.match(value):
            continue
        if value not in lines:
            lines.append(value)
    return "\n".join(lines)


def sanitize_site_title_suffix(title: str) -> str:
    return re.sub(r"\s*(?:[·|]|-)\s*GitBook\s*$", "", title, flags=re.IGNORECASE).strip()


@dataclass
class ExtractedPage:
    title: str
    text: str
    links: list[str]


class ContentExtractor:
    def extract(self, html: str, current_url: str) -> ExtractedPage:
        soup = BeautifulSoup(html, "html.parser")

        # Discover navigation before removing menus from readable content. Course sites such as
        # GitBook keep their full lesson catalog inside <nav>, which must be crawled but must not
        # pollute the lesson text stored in the knowledge base.
        links: list[str] = []
        for anchor in soup.select("a[href]"):
            href = anchor.get("href", "")
            absolute = urldefrag(urljoin(current_url, href))[0]
            if urlparse(absolute).scheme in {"http", "https"}:
                links.append(absolute)

        for node in soup.select("script, style, noscript, svg, nav, footer, header, button, input, select, textarea, .toolbar, .floating-controls, .site-chrome, .sidebar, .toc, .search"):
            node.decompose()

        content_root = soup.select_one(
            "main, article, [role='main'], .course-content, .lesson-content"
        )
        # Interactive course microsites often omit article/main. Fall back to the full
        # rendered body after chrome/control removal, rather than treating them as empty.
        root = content_root or soup.body or soup
        heading = root.select_one("h1") if hasattr(root, "select_one") else None
        title = sanitize_site_title_suffix(
            (heading.get_text(" ", strip=True) if heading else "")
            or (soup.title.get_text(" ", strip=True) if soup.title else "")
            or "未命名页面"
        )
        text = root.get_text("\n", strip=True)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        text = clean_course_content("\n".join(lines))

        return ExtractedPage(title=title[:500], text=text, links=list(dict.fromkeys(links)))
