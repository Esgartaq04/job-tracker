"""HTML cleaning and a small HTML→Markdown converter.

Descriptions are stored as Markdown so the detail drawer can render and edit them with
one editor, and so the LLM tier gets clean, cheap input (README §8.1).
"""

import html as html_lib
import re

from selectolax.parser import HTMLParser, Node

#: Chrome that carries no posting content and only inflates LLM input.
_NOISE_SELECTORS = (
    "script",
    "style",
    "noscript",
    "svg",
    "iframe",
    "nav",
    "header",
    "footer",
    "aside",
    "form",
    "[role=navigation]",
    "[role=banner]",
    "[role=contentinfo]",
    "[aria-hidden=true]",
    ".cookie",
    "#cookie-banner",
    ".cookie-banner",
    ".newsletter",
)

_CONTENT_SELECTORS = (
    "[data-testid=careerPage]",
    "article",
    "main",
    "[role=main]",
    "#content",
    ".job-description",
    "#job-description",
    ".posting",
    "#app-body",
    ".description",
    "section",
)

_BLOCK_TAGS = {"p", "div", "section", "article", "ul", "ol", "table", "tr", "blockquote"}
_HEADINGS = {"h1": "#", "h2": "##", "h3": "###", "h4": "####", "h5": "#####", "h6": "######"}


def _strip_noise(tree: HTMLParser) -> None:
    for selector in _NOISE_SELECTORS:
        for node in tree.css(selector):
            node.decompose()


def meta_fields(html: str) -> dict[str, str]:
    """og:*/twitter:*/<title> metadata, used by the generic tier."""
    tree = HTMLParser(html)
    found: dict[str, str] = {}
    for node in tree.css("meta"):
        attrs = node.attributes
        key = (attrs.get("property") or attrs.get("name") or "").lower()
        content = (attrs.get("content") or "").strip()
        if key and content:
            found.setdefault(key, content)
    title_node = tree.css_first("title")
    if title_node and title_node.text():
        found.setdefault("title", title_node.text().strip())
    canonical = tree.css_first("link[rel=canonical]")
    if canonical and canonical.attributes.get("href"):
        found.setdefault("canonical", canonical.attributes["href"].strip())
    return found


def main_content_html(html: str) -> str:
    """Readability-style main-content pick: strip chrome, then take the densest of a
    few likely containers, falling back to <body>."""
    tree = HTMLParser(html)
    _strip_noise(tree)

    best: Node | None = None
    best_length = 0
    for selector in _CONTENT_SELECTORS:
        for node in tree.css(selector):
            length = len(node.text(separator=" ", strip=True) or "")
            if length > best_length:
                best, best_length = node, length

    body = tree.body or tree.root

    # A container that holds most of the page's text is the page; prefer it only when
    # it is a genuine subset, otherwise keep the whole body.
    if best is not None and best_length >= 400:
        return best.html or ""
    return (body.html if body else html) or ""


def html_to_markdown(html: str) -> str:
    """Deliberately small: headings, lists, links, emphasis, paragraphs. Job postings
    do not need a full CommonMark writer, and a small one is easy to keep predictable."""
    if not html:
        return ""
    tree = HTMLParser(html)
    _strip_noise(tree)
    root = tree.body or tree.root
    if root is None:
        return ""
    rendered = _render(root).strip()
    return _collapse_blank_lines(rendered)


def html_to_text(html: str) -> str:
    if not html:
        return ""
    tree = HTMLParser(html)
    _strip_noise(tree)
    root = tree.body or tree.root
    text = root.text(separator=" ", strip=True) if root else ""
    return re.sub(r"[ \t]+", " ", text or "").strip()


def _render(node: Node, depth: int = 0) -> str:
    tag = node.tag
    if tag == "-text":
        raw = getattr(node, "text_content", None) or node.text() or ""
        return re.sub(r"\s+", " ", html_lib.unescape(raw))

    if tag == "br":
        return "\n"
    if tag in ("hr",):
        return "\n\n---\n\n"

    children = "".join(_render(child, depth + 1) for child in node.iter(include_text=True))

    if tag in _HEADINGS:
        text = children.strip()
        return f"\n\n{_HEADINGS[tag]} {text}\n\n" if text else ""
    if tag in ("strong", "b"):
        text = children.strip()
        return f"**{text}**" if text else ""
    if tag in ("em", "i"):
        text = children.strip()
        return f"*{text}*" if text else ""
    if tag == "code":
        text = children.strip()
        return f"`{text}`" if text else ""
    if tag == "a":
        href = node.attributes.get("href") or ""
        text = children.strip()
        if not text:
            return ""
        return f"[{text}]({href})" if href.startswith(("http", "mailto:")) else text
    if tag == "li":
        text = children.strip()
        return f"\n- {text}" if text else ""
    if tag in ("ul", "ol"):
        return f"\n{children.rstrip()}\n\n"
    if tag in _BLOCK_TAGS:
        text = children.strip()
        return f"\n\n{text}\n\n" if text else ""
    return children


def _collapse_blank_lines(text: str) -> str:
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()
