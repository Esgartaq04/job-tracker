/**
 * Autofill, the half that runs in the page (Phase 4b). Like `collectPosting`, both
 * functions are serialized into the tab by `chrome.scripting.executeScript`, so each
 * must stand alone: no imports, no closure over this module.
 *
 * The side panel runs `collectFormFields` in every frame it may read, sends the result
 * to the tracker for a plan, then runs `fillFields` with that plan. Neither function
 * submits anything, clicks a button, or presses Enter: the user reviews and submits.
 */

/** Describe the form controls on this page that are worth filling. */
export function collectFormFields() {
  const SKIP_TYPES = new Set(["hidden", "password", "submit", "button", "reset", "image", "search"]);
  const CAPTCHA = /captcha|recaptcha|hcaptcha|turnstile/i;

  const clean = (text) => (text || "").replace(/\s+/g, " ").replace(/\s*\*\s*$/, "").trim();

  function visible(el) {
    const style = getComputedStyle(el);
    if (style.visibility === "hidden" || style.display === "none") return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 || rect.height > 0;
  }

  function textOf(id) {
    return document.getElementById(id)?.innerText ?? "";
  }

  /** The words a person would read as this control's question. */
  function labelFor(el) {
    const parts = [];
    if (el.id) {
      for (const label of document.querySelectorAll(`label[for="${CSS.escape(el.id)}"]`)) {
        parts.push(label.innerText);
      }
    }
    const wrapping = el.closest("label");
    if (wrapping && !parts.length) parts.push(wrapping.innerText);
    const labelledBy = el.getAttribute("aria-labelledby");
    if (labelledBy) parts.push(labelledBy.split(/\s+/).map(textOf).join(" "));
    const aria = el.getAttribute("aria-label");
    if (aria) parts.push(aria);
    if (!parts.length) {
      // Unlabelled markup: the nearest container's own text usually holds the question.
      const container = el.closest("fieldset, .field, .form-group, li, div");
      const legend = container?.querySelector("legend, label, h3, h4, p");
      if (legend) parts.push(legend.innerText);
    }
    return clean(parts.join(" ")).slice(0, 300);
  }

  /** A radio or checkbox group is asked once: the fieldset's legend, or the text
   *  around the group, rather than any one option's label. */
  function groupQuestion(inputs) {
    const fieldset = inputs[0].closest("fieldset");
    const legend = fieldset?.querySelector("legend");
    if (legend) return clean(legend.innerText).slice(0, 300);
    const labelledBy = fieldset?.getAttribute("aria-labelledby") ||
      inputs[0].closest("[role=radiogroup], [role=group]")?.getAttribute("aria-labelledby");
    if (labelledBy) return clean(labelledBy.split(/\s+/).map(textOf).join(" ")).slice(0, 300);

    // Walk up until the container holds the whole group, then take its leading text.
    let container = inputs[0].parentElement;
    while (container && !inputs.every((input) => container.contains(input))) {
      container = container.parentElement;
    }
    const heading = container?.parentElement?.querySelector("label, legend, h3, h4, p");
    return clean(heading?.innerText ?? "").slice(0, 300);
  }

  function optionLabel(input) {
    return labelFor(input) || clean(input.value);
  }

  function fileRole(label) {
    if (/cover/i.test(label)) return "cover_letter";
    if (/resume|résumé|\bcv\b|curriculum/i.test(label)) return "resume";
    return "other";
  }

  const fields = [];
  const seenGroups = new Set();
  let next = 0;
  const tag = (el) => {
    const id = String(next++);
    el.setAttribute("data-jt-field", id);
    return id;
  };

  for (const el of document.querySelectorAll("input, textarea, select")) {
    el.removeAttribute("data-jt-field");
  }

  for (const el of document.querySelectorAll("input, textarea, select")) {
    const type = (el.getAttribute("type") || el.tagName).toLowerCase();
    if (SKIP_TYPES.has(type) || el.disabled || el.readOnly) continue;
    if (CAPTCHA.test(`${el.name} ${el.id} ${el.className}`)) continue;
    // File inputs are routinely hidden behind a styled "Attach" button; everything else
    // the user can't see, the user didn't mean to fill.
    if (type !== "file" && !visible(el)) continue;

    const base = {
      name: el.getAttribute("name") || null,
      html_id: el.id || null,
      input_type: type,
      autocomplete: el.getAttribute("autocomplete") || null,
      placeholder: el.getAttribute("placeholder") || null,
      required: el.required || el.getAttribute("aria-required") === "true",
    };

    if (type === "radio" || type === "checkbox") {
      const key = `${type}:${el.name || el.id}`;
      if (seenGroups.has(key)) continue;
      seenGroups.add(key);
      const group = el.name
        ? [...document.querySelectorAll(`input[type=${type}][name="${CSS.escape(el.name)}"]`)]
        : [el];
      if (group.some((input) => input.checked)) continue; // already answered
      const id = tag(el);
      for (const input of group) input.setAttribute("data-jt-field", id);
      fields.push({
        ...base,
        id,
        kind: type,
        label: group.length === 1 && type === "checkbox" ? labelFor(el) : groupQuestion(group),
        options: group.map(optionLabel).slice(0, 300),
        required: group.some((input) => input.required) || base.required,
      });
      continue;
    }

    if (el.tagName === "SELECT") {
      if (el.value && el.selectedIndex > 0) continue; // already chosen
      fields.push({
        ...base,
        id: tag(el),
        kind: "select",
        label: labelFor(el),
        options: [...el.options]
          .filter((option) => option.value !== "" && !option.disabled)
          .map((option) => clean(option.text))
          .slice(0, 300),
      });
      continue;
    }

    if (type === "file") {
      if (el.files?.length) continue;
      const label = labelFor(el);
      fields.push({ ...base, id: tag(el), kind: "file", label, file_role: fileRole(label) });
      continue;
    }

    if (el.value) continue; // never overwrite what's there
    fields.push({
      ...base,
      id: tag(el),
      kind: el.tagName === "TEXTAREA" ? "textarea" : "text",
      label: labelFor(el),
    });
  }

  // Forms embedded from another origin (a Greenhouse board inside a company site) are
  // only readable once that origin is granted; report them so the panel can ask.
  const frames =
    window === window.top
      ? [...document.querySelectorAll("iframe")]
          .filter(visible)
          .map((frame) => {
            try {
              return new URL(frame.src, location.href).origin;
            } catch {
              return null;
            }
          })
          .filter((origin) => origin && origin !== location.origin && /^https?:/.test(origin))
      : [];

  return { url: location.href, origin: location.origin, fields, frames: [...new Set(frames)] };
}

/**
 * Apply a plan from the tracker. `assignments` are `{ id, value?, attach? }`,
 * `needs` are ids to mark for the user, and `resume` is `{ name, type, base64 }`.
 * Returns what happened to each assignment.
 */
export function fillFields(assignments, needs, resume) {
  const FILLED = "2px solid #22c55e";
  const NEEDS_YOU = "2px solid #f59e0b";
  const results = [];

  const byId = (id) => [...document.querySelectorAll(`[data-jt-field="${CSS.escape(id)}"]`)];
  const norm = (text) =>
    (text || "").replace(/\s+/g, " ").replace(/\s*\*\s*$/, "").trim().toLowerCase();

  /**
   * React, Vue and Angular track an input's value themselves; assigning `el.value`
   * goes through the instance and the framework never notices. The prototype's setter
   * plus a bubbling `input` event is what typing produces.
   */
  function setValue(el, value) {
    const proto =
      el instanceof HTMLTextAreaElement
        ? HTMLTextAreaElement.prototype
        : el instanceof HTMLSelectElement
          ? HTMLSelectElement.prototype
          : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    el.dispatchEvent(new FocusEvent("blur"));
  }

  /** Outline what the user should look at: the control, or for a group of options
   *  (and a hidden file input) the smallest box that holds the whole question. */
  function mark(elements, outline) {
    if (!elements.length) return;
    let target = elements[0];
    if (elements.length > 1) {
      target = elements[0].parentElement;
      while (target && !elements.every((el) => target.contains(el))) target = target.parentElement;
    } else if (["file", "radio", "checkbox"].includes(target.type)) {
      target = target.closest("label, .field, .form-group, div") ?? target;
    }
    if (!target) return;
    target.style.outline = outline;
    target.style.outlineOffset = "2px";
  }

  function labelText(input) {
    const label =
      (input.id && document.querySelector(`label[for="${CSS.escape(input.id)}"]`)) ||
      input.closest("label");
    return norm(label?.innerText || input.value);
  }

  for (const assignment of assignments) {
    const elements = byId(assignment.id);
    const el = elements[0];
    if (!el) {
      results.push({ id: assignment.id, ok: false, reason: "the field is gone" });
      continue;
    }

    try {
      if (assignment.attach === "resume") {
        if (!resume) throw new Error("no resume loaded");
        const bytes = Uint8Array.from(atob(resume.base64), (c) => c.charCodeAt(0));
        const transfer = new DataTransfer();
        transfer.items.add(new File([bytes], resume.name, { type: resume.type }));
        el.files = transfer.files;
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
      } else if (el.tagName === "SELECT") {
        const wanted = norm(assignment.value);
        const option = [...el.options].find((o) => norm(o.text) === wanted || norm(o.value) === wanted);
        if (!option) throw new Error("no matching option");
        setValue(el, option.value);
      } else if (el.type === "radio" || el.type === "checkbox") {
        const wanted = norm(assignment.value);
        const choice =
          elements.length === 1 && el.type === "checkbox"
            ? /^(yes|true|on|checked)$/.test(wanted) || labelText(el) === wanted ? el : null
            : elements.find((input) => labelText(input) === wanted || norm(input.value) === wanted);
        if (!choice) throw new Error("no matching option");
        // A click is how frameworks hear about a choice. It's a radio or checkbox, not
        // a button, so it can't submit anything.
        if (!choice.checked) choice.click();
      } else {
        setValue(el, assignment.value ?? "");
      }
      mark(elements, FILLED);
      results.push({ id: assignment.id, ok: true });
    } catch (error) {
      mark(elements, NEEDS_YOU);
      results.push({ id: assignment.id, ok: false, reason: error.message });
    }
  }

  for (const id of needs) mark(byId(id), NEEDS_YOU);
  return results;
}
