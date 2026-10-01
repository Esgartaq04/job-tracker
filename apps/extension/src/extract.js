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
  /**
   * Which posting is on screen. Not simply the canonical link: list-and-detail boards
   * (Google Careers, LinkedIn and Indeed search) are single-page apps that swap the
   * job with `pushState` and never touch `<head>`, so the canonical link still names
   * whichever job the page first loaded. Trusting it saved that first job again for
   * every later click — and the server, deduplicating on the URL, said "saved".
   */
  function resolveUrl() {
    const here = new URL(location.href);
    const host = here.hostname.replace(/^www\./, "");

    // Boards whose selected job lives in a query parameter: name the job's own page.
    if (host.endsWith("linkedin.com")) {
      const id = here.searchParams.get("currentJobId");
      if (/^\d+$/.test(id ?? "")) {
        return { url: `https://www.linkedin.com/jobs/view/${id}`, headTrusted: false };
      }
    }
    if (host.endsWith("indeed.com")) {
      const id = here.searchParams.get("vjk") || here.searchParams.get("jk");
      if (/^[0-9a-f]+$/i.test(id ?? "")) {
        return { url: `https://www.indeed.com/viewjob?jk=${id}`, headTrusted: false };
      }
    }

    // A canonical link is only an upgrade when it describes this same page, minus noise
    // like tracking or search parameters. A different path means it went stale; so
    // does dropping a parameter that identifies the job — Google's apply page is
    // `/apply?jobId=…`, and a canonical without the `jobId` names every job at once.
    const canonicalHref = document.querySelector("link[rel=canonical]")?.href;
    if (canonicalHref) {
      try {
        const canonical = new URL(canonicalHref);
        const samePath =
          canonical.origin === here.origin &&
          canonical.pathname.replace(/\/+$/, "") === here.pathname.replace(/\/+$/, "");
        const keepsIdentity = [...here.searchParams].every(
          ([key, value]) => isNoise(key) || canonical.searchParams.get(key) === value,
        );
        return samePath && keepsIdentity
          ? { url: canonical.href, headTrusted: true }
          : { url: here.href, headTrusted: false };
      } catch {
        // An unparseable canonical link is no evidence either way.
      }
    }
    return { url: here.href, headTrusted: true };
  }

  /** Query parameters that never identify a posting: tracking, and the search that
   *  led here. Mirrors the server's TRACKING_PARAMS (services/ingestion/normalize.py). */
  function isNoise(key) {
    const lowered = key.toLowerCase();
    return (
      /^(utm_|spa_|_hs)/.test(lowered) ||
      [
        "gh_src", "refid", "ref", "referrer", "trk", "trackingid", "trackingsource", "src",
        "source", "fbclid", "gclid", "msclkid", "mc_cid", "mc_eid", "lever-origin",
        "lever-source", "ashby_jid_source", "q", "query", "keywords", "location", "l",
        "loc", "page", "start", "sort", "from", "hl",
      ].includes(lowered)
    );
  }

  /**
   * Trim the DOM to something worth sending: no scripts, styles, or SVG payloads.
   * When the head is stale, its metadata describes a different job, so that goes too —
   * otherwise the server's JSON-LD and og: readers would rebuild the first job's card
   * from the second job's page.
   */
  function cleanedHtml(headTrusted) {
    const clone = document.documentElement.cloneNode(true);
    for (const node of clone.querySelectorAll("script:not([type='application/ld+json']), style, svg, canvas, video, iframe, link[rel=stylesheet]")) {
      node.remove();
    }
    if (!headTrusted) {
      const stale = clone.querySelectorAll(
        "link[rel=canonical], meta[property^='og:'], meta[name^='twitter:'], head script[type='application/ld+json']",
      );
      for (const node of stale) node.remove();
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

    if (host === "google.com" && location.pathname.startsWith("/about/careers")) {
      // The page's first <h1> reads "job details" and the detail pane's class names are
      // generated, but the app keeps the tab title in step with the open job — and the
      // apply form carries the title in its own URL.
      const fromUrl = new URL(location.href).searchParams.get("title");
      const fromTab = document.title.replace(/\s*[—–-]\s*Google Careers\s*$/i, "").trim();
      const generic = /^(search jobs|jobs search results|google careers|apply|job details)$/i;
      return {
        title: fromUrl || (fromTab && !generic.test(fromTab) ? fromTab : null),
        company: "Google",
        location: null,
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
  const { url, headTrusted } = resolveUrl();

  return {
    url,
    html: cleanedHtml(headTrusted),
    hints,
    // A visible-text fallback so the manual tier has something even if the HTML is
    // too exotic for the readability pass.
    text: document.body?.innerText?.slice(0, 100_000) ?? "",
  };
}
