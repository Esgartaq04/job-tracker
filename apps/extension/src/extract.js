/**
 * Runs in the page, not the extension: this is what `chrome.scripting.executeScript`
 * injects when you click the toolbar button.
 *
 * It does not parse the posting — the server's tier stack already knows how to do that,
 * and duplicating it here would mean two implementations drifting apart. All this does
 * is hand over the rendered DOM the user is already looking at, plus whatever the page
 * states about itself, so the same pipeline runs against a site that blocks
 * server-side fetching (README §4.1, mitigation 1).
 */
export function collectPosting() {
  /** Trim the DOM to something worth sending: no scripts, styles, or SVG payloads. */
  function cleanedHtml() {
    const clone = document.documentElement.cloneNode(true);
    for (const node of clone.querySelectorAll("script:not([type='application/ld+json']), style, svg, canvas, video, iframe, link[rel=stylesheet]")) {
      node.remove();
    }
    return clone.outerHTML;
  }

  /**
   * Site-specific hints. These are *hints* — the server treats them as one more
   * candidate, so a stale selector degrades to "no hint", never to a wrong record.
   */
  function siteHints() {
    const host = location.hostname.replace(/^www\./, "");

    if (host.endsWith("linkedin.com")) {
      return {
        title: text(".job-details-jobs-unified-top-card__job-title, .topcard__title, h1"),
        company: text(
          ".job-details-jobs-unified-top-card__company-name, .topcard__org-name-link, .topcard__flavor",
        ),
        location: text(
          ".job-details-jobs-unified-top-card__bullet, .topcard__flavor--bullet",
        ),
      };
    }

    if (host.endsWith("indeed.com")) {
      return {
        title: text("h1.jobsearch-JobInfoHeader-title, [data-testid=jobsearch-JobInfoHeader-title]"),
        company: text("[data-testid=inlineHeader-companyName], [data-company-name]"),
        location: text("[data-testid=inlineHeader-companyLocation], [data-testid=job-location]"),
      };
    }

    if (host.endsWith("glassdoor.com")) {
      return {
        title: text("[data-test=job-title], h1"),
        company: text("[data-test=employer-name]"),
        location: text("[data-test=location]"),
      };
    }

    return {
      title: text("h1"),
      company: meta("og:site_name"),
      location: null,
    };
  }

  function text(selector) {
    const node = document.querySelector(selector);
    const value = node?.textContent?.trim().replace(/\s+/g, " ");
    return value && value.length < 200 ? value : null;
  }

  function meta(property) {
    return (
      document
        .querySelector(`meta[property="${property}"], meta[name="${property}"]`)
        ?.getAttribute("content")
        ?.trim() || null
    );
  }

  const hints = siteHints();

  return {
    // The canonical link, when the page publishes one, is a better dedup key than
    // whatever tracking-laden URL the user happens to be on.
    url: document.querySelector("link[rel=canonical]")?.href || location.href,
    html: cleanedHtml(),
    hints,
    // A visible-text fallback so the manual tier has something even if the HTML is
    // too exotic for the readability pass.
    text: document.body?.innerText?.slice(0, 100_000) ?? "",
  };
}
