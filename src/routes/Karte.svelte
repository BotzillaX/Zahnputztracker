<script>
  import { onMount } from "svelte";
  import { requestBlobUrl } from "../lib/api/client.js";
  import { gibNetzFrei, ladeKarte, oeffneKopie, vergissAnsicht } from "../lib/api/service.js";

  const namen = { search: "Such-Browser", session: "Sitzungs-Browser" };

  // Masse des Rasters. Ein Knoten ist so breit, dass eine gekuerzte
  // Adresse hineinpasst, und der Abstand so gross, dass die Beschriftung
  // einer Kante zwischen zwei Spalten Platz hat.
  const BREITE = 190;
  const HOEHE = 46;
  const SPALTE = 280;
  const ZEILE = 78;
  const RAND = 24;

  let bereich = $state("session");
  let karte = $state({ views: [], steps: [], current: {} });
  let gewaehlt = $state("");
  let bilder = $state({});
  let meldung = $state("");
  let fehler = $state("");
  let beschaeftigt = $state("");

  onMount(() => {
    laden();
    const takt = setInterval(laden, 5000);
    return () => clearInterval(takt);
  });

  async function laden() {
    try {
      karte = await ladeKarte(bereich);
    } catch (e) {
      fehler = String(e.message ?? e);
    }
  }

  async function fuehreAus(name, aufgabe) {
    fehler = "";
    meldung = "";
    beschaeftigt = name;
    try {
      await aufgabe();
      await laden();
    } catch (e) {
      fehler = String(e.message ?? e);
    } finally {
      beschaeftigt = "";
    }
  }

  function wechsle(neu) {
    bereich = neu;
    gewaehlt = "";
    laden();
  }

  /** Der Teil der Adresse, der eine Ansicht wiedererkennbar macht. */
  function kurz(adresse, kennung) {
    if (!adresse) return kennung.slice(0, 8);
    try {
      const url = new URL(adresse);
      const pfad = (url.pathname + url.search).replace(/\/$/, "") || "/";
      return pfad.length > 30 ? pfad.slice(0, 29) + "…" : pfad;
    } catch {
      return adresse.slice(0, 30);
    }
  }

  /**
   * Spaltenweise Anordnung: eine Ansicht steht so weit rechts, wie sie
   * Schritte von einem Anfang entfernt ist. Anfang ist jede Ansicht, in
   * die kein beobachteter Schritt hineinfuehrt. Ansichten, die in keinem
   * Schritt vorkommen, bekommen eine eigene Spalte ganz links: sie sind
   * gesehen worden, aber es ist nicht aufgezeichnet, wie man hinkommt.
   */
  const plan = $derived.by(() => {
    const ansichten = karte.views ?? [];
    const schritte = (karte.steps ?? []).filter(
      (s) => ansichten.some((a) => a.view === s.from) && ansichten.some((a) => a.view === s.to)
    );
    const hinein = new Map();
    const hinaus = new Map();
    for (const schritt of schritte) {
      hinein.set(schritt.to, (hinein.get(schritt.to) ?? 0) + 1);
      if (!hinaus.has(schritt.from)) hinaus.set(schritt.from, []);
      hinaus.get(schritt.from).push(schritt.to);
    }

    const ebene = new Map();
    const einzeln = ansichten.filter((a) => !hinein.has(a.view) && !hinaus.has(a.view));
    const anfaenge = ansichten.filter((a) => !hinein.has(a.view) && hinaus.has(a.view));
    let welle = anfaenge.map((a) => a.view);
    welle.forEach((v) => ebene.set(v, 0));
    let stufe = 0;
    while (welle.length && stufe < 40) {
      const naechste = [];
      for (const knoten of welle) {
        for (const ziel of hinaus.get(knoten) ?? []) {
          if (ebene.has(ziel)) continue;
          ebene.set(ziel, stufe + 1);
          naechste.push(ziel);
        }
      }
      welle = naechste;
      stufe += 1;
    }
    // Alles, was nur in einem Kreis vorkommt, hat noch keine Ebene.
    for (const a of ansichten) {
      if (!ebene.has(a.view) && !einzeln.includes(a)) ebene.set(a.view, stufe + 1);
    }

    const spalten = new Map();
    for (const a of einzeln) {
      if (!spalten.has(-1)) spalten.set(-1, []);
      spalten.get(-1).push(a);
    }
    for (const a of ansichten) {
      if (einzeln.includes(a)) continue;
      const s = ebene.get(a.view) ?? 0;
      if (!spalten.has(s)) spalten.set(s, []);
      spalten.get(s).push(a);
    }

    const stellen = new Map();
    const knoten = [];
    const reihenfolge = [...spalten.keys()].sort((a, b) => a - b);
    reihenfolge.forEach((s, spaltennummer) => {
      spalten.get(s).forEach((a, zeile) => {
        const x = RAND + spaltennummer * SPALTE;
        const y = RAND + zeile * ZEILE;
        stellen.set(a.view, { x, y });
        knoten.push({ ...a, x, y, ohneWeg: s === -1 });
      });
    });

    const kanten = schritte
      .map((schritt) => {
        const von = stellen.get(schritt.from);
        const nach = stellen.get(schritt.to);
        if (!von || !nach) return null;
        return {
          ...schritt,
          x1: von.x + BREITE,
          y1: von.y + HOEHE / 2,
          x2: nach.x,
          y2: nach.y + HOEHE / 2
        };
      })
      .filter(Boolean);

    const breite = RAND * 2 + reihenfolge.length * SPALTE;
    const hoehe =
      RAND * 2 + Math.max(1, ...reihenfolge.map((s) => spalten.get(s).length)) * ZEILE;
    return { knoten, kanten, breite, hoehe };
  });

  const offen = $derived((karte.views ?? []).find((a) => a.view === gewaehlt) ?? null);
  const hinKanten = $derived((karte.steps ?? []).filter((s) => s.to === gewaehlt));
  const wegKanten = $derived((karte.steps ?? []).filter((s) => s.from === gewaehlt));

  async function waehle(kennung) {
    gewaehlt = gewaehlt === kennung ? "" : kennung;
    const ansicht = (karte.views ?? []).find((a) => a.view === gewaehlt);
    if (!ansicht || bilder[gewaehlt] || !ansicht.has_screenshot) return;
    try {
      bilder[gewaehlt] = await requestBlobUrl(`/atlas/${ansicht.scope}/${ansicht.view}/screenshot`);
    } catch (e) {
      fehler = String(e.message ?? e);
    }
  }

  const kopie = (ansicht) =>
    fuehreAus("kopie", async () => {
      const ergebnis = await oeffneKopie("search", ansicht.view, ansicht.scope);
      meldung =
        "Kopie im Such-Browser geöffnet (ohne Skript, ohne Netz). Der Auswahlmodus " +
        "arbeitet dort wie auf der echten Seite. " + ergebnis.file;
    });
</script>

<div class="seite">
  <section>
    <h2>Karte der Ansichten</h2>
    <p class="hinweis">
      Jeder Kasten ist eine Ansicht, die wirklich gesehen wurde. Jeder Pfeil ist ein beobachteter
      Schritt von einer Ansicht zur nächsten, beschriftet mit dem Auslöser. Was hier steht, ist
      gemessen und nicht geraten: eine Verbindung ohne Pfeil ist bisher nie vorgekommen.
    </p>
    <div class="knoepfe">
      <button class:aktiv={bereich === "session"} onclick={() => wechsle("session")}>
        Sitzungs-Browser
      </button>
      <button class:aktiv={bereich === "search"} onclick={() => wechsle("search")}>
        Such-Browser
      </button>
      <span class="fueller"></span>
      <button onclick={() => fuehreAus("frei", () => gibNetzFrei("search"))}>
        Netzsperre aufheben
      </button>
    </div>
    {#if meldung}<p class="ok">{meldung}</p>{/if}
    {#if fehler}<p class="bad">{fehler}</p>{/if}
    <p class="hinweis">
      {plan.knoten.length} Ansicht(en), {plan.kanten.length} Übergang(e) im
      {namen[bereich]}
    </p>
  </section>

  {#if plan.knoten.length === 0}
    <p class="hinweis">
      Noch nichts aufgezeichnet. Der Katalog füllt sich von selbst, sobald der Browser läuft und
      Seiten wechselt.
    </p>
  {:else}
    <div class="rahmen">
      <svg width={plan.breite} height={plan.hoehe} role="img" aria-label="Karte der Ansichten">
        <defs>
          <marker id="spitze" markerWidth="8" markerHeight="8" refX="7" refY="3"
                  orient="auto" markerUnits="strokeWidth">
            <path d="M0,0 L7,3 L0,6 z" fill="var(--muted)" />
          </marker>
        </defs>
        {#each plan.kanten as kante}
          {@const betont = kante.from === gewaehlt || kante.to === gewaehlt}
          <path
            d={`M ${kante.x1} ${kante.y1} C ${kante.x1 + 45} ${kante.y1}, ${kante.x2 - 45} ${kante.y2}, ${kante.x2} ${kante.y2}`}
            fill="none"
            stroke={betont ? "var(--ok)" : "var(--line)"}
            stroke-width={betont ? 2 : 1}
            marker-end="url(#spitze)"
          />
          <text
            class="kante"
            x={(kante.x1 + kante.x2) / 2}
            y={(kante.y1 + kante.y2) / 2 - 5}
            text-anchor="middle"
          >
            {kante.trigger} ({kante.count}×)
          </text>
        {/each}
        {#each plan.knoten as k}
          <g
            class="knoten"
            class:gewaehlt={k.view === gewaehlt}
            onclick={() => waehle(k.view)}
            onkeydown={(e) => e.key === "Enter" && waehle(k.view)}
            role="button"
            tabindex="0"
          >
            <rect x={k.x} y={k.y} width={BREITE} height={HOEHE} rx="6" />
            <text class="titel" x={k.x + 10} y={k.y + 19}>{kurz(k.url, k.view)}</text>
            <text class="unten" x={k.x + 10} y={k.y + 35}>
              {k.count}× gesehen · {k.elements} Elemente{k.ohneWeg ? " · ohne bekannten Weg" : ""}
            </text>
            {#if karte.current?.[k.scope] === k.view}
              <circle cx={k.x + BREITE - 12} cy={k.y + 12} r="4" fill="var(--ok)" />
            {/if}
          </g>
        {/each}
      </svg>
    </div>
  {/if}

  {#if offen}
    <section class="karte">
      <div class="zeile">
        <strong>{kurz(offen.url, offen.view)}</strong>
        <code class="muted">{offen.view}</code>
        <span class="fueller"></span>
        <button onclick={() => kopie(offen)} disabled={!offen.has_snapshot || beschaeftigt === "kopie"}>
          Kopie im Picker öffnen
        </button>
        <button onclick={() => fuehreAus("vergessen", () => vergissAnsicht(offen.scope, offen.view))}>
          vergessen
        </button>
      </div>
      <p class="hinweis">
        zuerst gesehen {offen.first_seen} · zuletzt {offen.last_seen} · {offen.count}× ·
        erreicht über {(offen.arrivals ?? []).join(", ") || "(nichts vermerkt)"}
      </p>
      <p class="pfad">{offen.url}</p>
      <div class="spalten">
        <div>
          <h3>Führt hierher</h3>
          {#if hinKanten.length === 0}
            <p class="hinweis">Kein Schritt aufgezeichnet.</p>
          {:else}
            <ul>
              {#each hinKanten as s}
                <li>
                  <button class="verweis" onclick={() => waehle(s.from)}>
                    {kurz((karte.views ?? []).find((a) => a.view === s.from)?.url ?? "", s.from)}
                  </button>
                  <span class="muted">{s.trigger} · {s.count}× · zuerst {s.first_seen}</span>
                </li>
              {/each}
            </ul>
          {/if}
        </div>
        <div>
          <h3>Führt weiter nach</h3>
          {#if wegKanten.length === 0}
            <p class="hinweis">Kein Schritt aufgezeichnet.</p>
          {:else}
            <ul>
              {#each wegKanten as s}
                <li>
                  <button class="verweis" onclick={() => waehle(s.to)}>
                    {kurz((karte.views ?? []).find((a) => a.view === s.to)?.url ?? "", s.to)}
                  </button>
                  <span class="muted">{s.trigger} · {s.count}× · zuerst {s.first_seen}</span>
                </li>
              {/each}
            </ul>
          {/if}
        </div>
      </div>
      {#if bilder[offen.view]}
        <img src={bilder[offen.view]} alt="Bild der Ansicht" />
      {/if}
    </section>
  {/if}
</div>

<style>
  .seite { display: flex; flex-direction: column; gap: 18px; padding-bottom: 40px; }
  section { display: flex; flex-direction: column; gap: 8px; }
  h2 {
    font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--muted); margin: 0; padding-bottom: 6px; border-bottom: 1px solid var(--line);
  }
  h3 { font-size: 12px; color: var(--muted); margin: 0 0 4px; font-weight: 600; }
  .rahmen {
    border: 1px solid var(--line); border-radius: 8px; background: var(--panel);
    overflow: auto; max-height: 460px;
  }
  .knoten rect { fill: var(--bg); stroke: var(--line); }
  .knoten:hover rect { stroke: var(--muted); }
  .knoten.gewaehlt rect { stroke: var(--ok); stroke-width: 2; }
  .knoten { cursor: pointer; }
  .titel { font-size: 12px; fill: var(--text); }
  .unten { font-size: 10px; fill: var(--muted); }
  .kante { font-size: 10px; fill: var(--muted); }
  .karte { border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; background: var(--panel); }
  .knoepfe { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  .knoepfe button.aktiv { border-color: var(--ok); color: var(--text); }
  .zeile { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; font-size: 13px; }
  .spalten { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 8px; }
  .fueller { flex: 1; }
  ul { list-style: none; padding: 0; margin: 0; font-size: 12px; }
  li { padding: 2px 0; display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
  .verweis {
    background: transparent; border: none; color: var(--text); padding: 0;
    text-decoration: underline; cursor: pointer; font-size: 12px;
  }
  img { max-width: 100%; border: 1px solid var(--line); border-radius: 6px; margin-top: 8px; }
  code { font-size: 12px; }
  .hinweis { font-size: 12px; color: var(--muted); margin: 0; }
  .pfad { font-size: 11px; color: var(--muted); word-break: break-all; margin: 0; }
  .muted { color: var(--muted); }
  .ok { color: var(--ok); font-size: 13px; margin: 0; }
  .bad { color: var(--bad); font-size: 13px; margin: 0; }
</style>
