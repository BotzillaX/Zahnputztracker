// Selection overlay, injected into every document of both browser
// instances (specification 2.5).
//
// Three jobs, deliberately in one file so a single init script is
// enough:
//   1. let the user point at an element and confirm it
//   2. build the recognition candidates of that element (2.4)
//   3. find an element again from stored candidates, at run time
//
// Nothing in here knows anything about a particular page. Every value
// it produces is read from the document in front of it.
//
// Every node this file creates carries the marker attribute, so it can
// be removed from snapshots and hidden before screenshots. The overlay
// must never be part of saved diagnostic material.

(() => {
  if (window.__ztOverlay) return;

  const MARK = "data-zt-ui";
  const HIT = "data-zt-hit";
  const MAX_TEXT = 80;
  const MAX_PATH_DEPTH = 4;

  // ------------------------------------------------------------ utilities

  const own = (element) => element.hasAttribute && element.hasAttribute(MARK);

  function visible(element) {
    if (!(element instanceof Element)) return false;
    if (!element.getClientRects().length) return false;
    const style = getComputedStyle(element);
    if (style.visibility === "hidden" || style.display === "none") return false;
    if (Number(style.opacity) === 0) return false;
    return true;
  }

  function text(element) {
    return (element.textContent || "").replace(/\s+/g, " ").trim();
  }

  /** An identifier that looks machine made is worthless tomorrow. */
  function generated(value) {
    if (!value || value.length > 40) return true;
    if (/^\s*$/.test(value)) return true;
    if (/\d{3,}/.test(value)) return true;
    if (/[0-9a-f]{6,}/i.test(value)) return true;
    if (/^[:_]|[:_]$/.test(value)) return true;
    if (/^(radix|headless|mui|ember|react|svelte|vue)[-_:]?\d*/i.test(value)) return true;
    return false;
  }

  /** Class names that carry meaning, hashed build output dropped. */
  function stableClasses(element) {
    return Array.from(element.classList || [])
      .filter((name) => name.length <= 30 && !/[0-9a-f]{5,}/i.test(name) && !/\d{3,}/.test(name))
      .slice(0, 2);
  }

  const IMPLICIT_ROLES = {
    a: "link",
    button: "button",
    select: "combobox",
    textarea: "textbox",
    h1: "heading",
    h2: "heading",
    h3: "heading",
    h4: "heading",
    h5: "heading",
    h6: "heading",
    nav: "navigation",
    form: "form",
    img: "img"
  };

  function ariaRole(element) {
    const explicit = (element.getAttribute("role") || "").trim();
    if (explicit) return explicit;
    const tag = element.tagName.toLowerCase();
    if (tag === "a") return element.hasAttribute("href") ? "link" : "";
    if (tag === "input") {
      const type = (element.getAttribute("type") || "text").toLowerCase();
      if (["button", "submit", "reset"].includes(type)) return "button";
      if (type === "checkbox") return "checkbox";
      if (type === "radio") return "radio";
      return "textbox";
    }
    return IMPLICIT_ROLES[tag] || "";
  }

  function accessibleName(element) {
    const label = element.getAttribute("aria-label");
    if (label && label.trim()) return label.trim();
    const by = element.getAttribute("aria-labelledby");
    if (by) {
      const parts = by
        .split(/\s+/)
        .map((id) => document.getElementById(id))
        .filter(Boolean)
        .map((node) => text(node));
      if (parts.join(" ").trim()) return parts.join(" ").trim();
    }
    if (element.id) {
      const bound = document.querySelector(`label[for="${CSS.escape(element.id)}"]`);
      if (bound && text(bound)) return text(bound);
    }
    for (const name of ["alt", "title", "placeholder"]) {
      const value = element.getAttribute(name);
      if (value && value.trim()) return value.trim();
    }
    const content = text(element);
    if (content && content.length <= MAX_TEXT) return content;
    return "";
  }

  /** All data attributes of an element, testing conventions first. */
  function dataAttributes(element) {
    const found = [];
    for (const attribute of Array.from(element.attributes)) {
      if (!attribute.name.startsWith("data-")) continue;
      const value = (attribute.value || "").trim();
      if (!value || value.length > 60 || /\s/.test(value)) continue;
      const hint = /(test|qa|cy|automation|tid)/i.test(attribute.name) ? 0 : 1;
      found.push({ name: attribute.name, value, hint });
    }
    found.sort((a, b) => a.hint - b.hint);
    return found;
  }

  function shortPath(element) {
    const steps = [];
    let node = element;
    let depth = 0;
    while (node && node.nodeType === 1 && depth < MAX_PATH_DEPTH) {
      const tag = node.tagName.toLowerCase();
      if (tag === "html" || tag === "body") break;
      const classes = stableClasses(node);
      let step = tag + classes.map((name) => "." + CSS.escape(name)).join("");
      const parent = node.parentElement;
      if (parent) {
        const twins = Array.from(parent.children).filter((child) => child.tagName === node.tagName);
        if (twins.length > 1) step += `:nth-of-type(${twins.indexOf(node) + 1})`;
      }
      steps.unshift(step);
      // A node with an own hook ends the path: the hook replaces the
      // step of that node, it is not written in addition to it.
      if (node.id && !generated(node.id)) {
        steps[0] = "#" + CSS.escape(node.id);
        break;
      }
      const data = dataAttributes(node)[0];
      if (data && node !== element) {
        steps[0] = `[${data.name}="${data.value}"]`;
        break;
      }
      node = node.parentElement;
      depth += 1;
    }
    return steps.join(" > ");
  }

  // -------------------------------------------------------- candidates (2.4)

  function candidates(element) {
    const list = [];
    for (const data of dataAttributes(element)) {
      list.push({ kind: "attr", attr: data.name, value: data.value });
    }
    const role = ariaRole(element);
    const name = accessibleName(element);
    if (role && name) list.push({ kind: "aria", role, value: name });
    const content = text(element);
    if (content && content.length <= MAX_TEXT) list.push({ kind: "text", value: content });
    if (element.id && !generated(element.id)) list.push({ kind: "id", value: element.id });
    const path = shortPath(element);
    if (path) list.push({ kind: "path", value: path });
    return list;
  }

  function attributesOf(element) {
    return Array.from(element.attributes)
      .filter((attribute) => attribute.name !== MARK && attribute.name !== HIT)
      .map((attribute) => ({ name: attribute.name, value: attribute.value }));
  }

  /** Every option of a selection field, so a value can be chosen later. */
  function optionsOf(element) {
    if (element.tagName.toLowerCase() !== "select") return [];
    return Array.from(element.options).map((option) => ({
      value: option.value,
      display: (option.textContent || "").trim()
    }));
  }

  function describe(element) {
    return {
      tag: element.tagName.toLowerCase(),
      text: text(element).slice(0, 200),
      visible: visible(element),
      attributes: attributesOf(element),
      options: optionsOf(element),
      candidates: candidates(element),
      path: shortPath(element),
      url: location.href
    };
  }

  // ------------------------------------------------------------ finding (2.4)

  function matchesOf(candidate) {
    const all = Array.from(document.querySelectorAll("*")).filter((node) => !own(node));
    if (candidate.kind === "attr") {
      return all.filter((node) => node.getAttribute(candidate.attr) === candidate.value);
    }
    if (candidate.kind === "id") {
      return all.filter((node) => node.id === candidate.value);
    }
    if (candidate.kind === "aria") {
      return all.filter(
        (node) => ariaRole(node) === candidate.role && accessibleName(node) === candidate.value
      );
    }
    if (candidate.kind === "text") {
      // The deepest element carrying exactly this text, not its wrappers.
      const hits = all.filter((node) => text(node) === candidate.value);
      return hits.filter((node) => !hits.some((other) => other !== node && node.contains(other)));
    }
    if (candidate.kind === "path") {
      try {
        return Array.from(document.querySelectorAll(candidate.value)).filter((node) => !own(node));
      } catch (error) {
        return [];
      }
    }
    return [];
  }

  /**
   * Resolution rule from 2.4: the visible element wins, several visible
   * ones are not a decision this program is allowed to make.
   */
  function find(candidate, wantAll) {
    const hits = matchesOf(candidate);
    const shown = hits.filter(visible);
    const result = { total: hits.length, visible: shown.length, marked: 0 };
    clearHit();
    if (wantAll) {
      shown.forEach((node, index) => node.setAttribute(HIT, String(index)));
      result.marked = shown.length;
      return result;
    }
    if (shown.length === 1) {
      shown[0].setAttribute(HIT, "0");
      result.marked = 1;
    }
    return result;
  }

  function clearHit() {
    for (const node of Array.from(document.querySelectorAll(`[${HIT}]`))) {
      node.removeAttribute(HIT);
    }
  }

  // ------------------------------------------------ page catalogue and copies

  /**
   * Structural signature of the current view: which kinds of elements
   * are visible, not what they say. Two views with the same structure
   * count as the same view even if the texts differ.
   */
  function signature() {
    const counted = new Map();
    for (const node of Array.from(document.querySelectorAll("*"))) {
      if (own(node) || !visible(node)) continue;
      const data = dataAttributes(node)
        .map((entry) => entry.name)
        .join(",");
      const part = `${node.tagName.toLowerCase()}|${ariaRole(node)}|${data}`;
      counted.set(part, (counted.get(part) || 0) + 1);
    }
    return Array.from(counted.entries())
      .sort((a, b) => (a[0] < b[0] ? -1 : 1))
      .map(([part, count]) => `${part}#${count}`)
      .join("\n");
  }

  /** Document copy without a trace of this overlay. */
  function snapshot() {
    const copy = document.documentElement.cloneNode(true);
    for (const node of Array.from(copy.querySelectorAll(`[${MARK}], [${HIT}]`))) {
      if (node.hasAttribute(MARK)) node.remove();
      else node.removeAttribute(HIT);
    }
    return "<!doctype html>\n" + copy.outerHTML;
  }

  // ---------------------------------------------------------------- the tool

  let box = null;
  let bar = null;
  let current = null;
  let active = false;

  function build() {
    if (box && box.isConnected) return;
    box = document.createElement("div");
    box.setAttribute(MARK, "1");
    box.style.cssText =
      "position:fixed;pointer-events:none;z-index:2147483646;border:2px solid #3b82f6;" +
      "background:rgba(59,130,246,0.12);border-radius:2px;display:none";
    bar = document.createElement("div");
    bar.setAttribute(MARK, "1");
    bar.style.cssText =
      "position:fixed;left:12px;bottom:12px;z-index:2147483647;pointer-events:none;" +
      "background:#0b1220;color:#e5e7eb;font:12px/1.5 system-ui,sans-serif;padding:6px 10px;" +
      "border:1px solid #334155;border-radius:6px;max-width:70vw;display:none";
    document.documentElement.appendChild(box);
    document.documentElement.appendChild(bar);
  }

  const HINT =
    "Pfeil hoch/runter: Ebene wechseln, Pfeil links/rechts: Nachbar, Enter: übernehmen, Esc: abbrechen";

  function paint() {
    if (!current) {
      box.style.display = "none";
      return;
    }
    const rect = current.getBoundingClientRect();
    box.style.display = "block";
    box.style.left = `${rect.left}px`;
    box.style.top = `${rect.top}px`;
    box.style.width = `${rect.width}px`;
    box.style.height = `${rect.height}px`;
    const label = text(current).slice(0, 40);
    bar.textContent =
      `Auswahl: <${current.tagName.toLowerCase()}>` + (label ? ` "${label}"` : "") + "   " + HINT;
  }

  function onMove(event) {
    if (!active) return;
    const element = document.elementFromPoint(event.clientX, event.clientY);
    if (!element || own(element)) return;
    current = element;
    paint();
  }

  function onClick(event) {
    if (!active) return;
    event.preventDefault();
    event.stopPropagation();
    const element = document.elementFromPoint(event.clientX, event.clientY);
    if (element && !own(element)) {
      current = element;
      paint();
    }
  }

  function onKey(event) {
    if (!active) {
      // Hotkey from 2.5, next to the button in the application.
      if (event.ctrlKey && event.shiftKey && String(event.key).toLowerCase() === "y") {
        event.preventDefault();
        start();
      }
      return;
    }
    const keys = ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Enter", "Escape"];
    if (!keys.includes(event.key)) return;
    event.preventDefault();
    event.stopPropagation();
    if (event.key === "Escape") {
      report({ type: "pick_cancelled" });
      stop();
      return;
    }
    if (event.key === "Enter") {
      if (current) report({ type: "pick", element: describe(current) });
      stop();
      return;
    }
    if (!current) return;
    if (event.key === "ArrowUp" && current.parentElement && !own(current.parentElement)) {
      current = current.parentElement;
    } else if (event.key === "ArrowDown") {
      const child = Array.from(current.children).find((node) => !own(node));
      if (child) current = child;
    } else if (current.parentElement) {
      const siblings = Array.from(current.parentElement.children).filter((node) => !own(node));
      const at = siblings.indexOf(current);
      const step = event.key === "ArrowLeft" ? -1 : 1;
      const next = siblings[(at + step + siblings.length) % siblings.length];
      if (next) current = next;
    }
    paint();
  }

  function report(message) {
    try {
      if (window.__ztAssist) window.__ztAssist({ ...message, url: location.href });
    } catch (error) {
      /* the service is not listening, the overlay still works */
    }
  }

  function start() {
    build();
    arm();
    active = true;
    current = null;
    box.style.display = "none";
    bar.style.display = "block";
    bar.textContent = "Auswahlmodus aktiv. Element anfahren, " + HINT;
    report({ type: "picker_state", active: true });
  }

  function stop() {
    active = false;
    current = null;
    if (box) box.style.display = "none";
    if (bar) bar.style.display = "none";
    report({ type: "picker_state", active: false });
  }

  function hide() {
    if (box) box.style.visibility = "hidden";
    if (bar) bar.style.visibility = "hidden";
  }

  function show() {
    if (box) box.style.visibility = "visible";
    if (bar) bar.style.visibility = "visible";
  }

  /**
   * Hang the handlers into the document. Called again on every start:
   * a document that is rewritten in place (document.open) loses its
   * listeners while this script stays alive. Adding the same function
   * twice is a no-op, so this is safe to repeat.
   */
  function arm() {
    document.addEventListener("mousemove", onMove, true);
    document.addEventListener("click", onClick, true);
    document.addEventListener("keydown", onKey, true);
  }

  arm();

  window.__ztOverlay = {
    arm,
    start,
    stop,
    hide,
    show,
    describe,
    find,
    clearHit,
    signature,
    snapshot,
    get active() {
      return active;
    }
  };
})();
