<script>
  import { onMount } from "svelte";
  import { requestBlobUrl } from "../lib/api/client.js";
  import {
    gibNetzFrei,
    ladeAnsichten,
    merkeAnsicht,
    oeffneKopie,
    vergissAnsicht
  } from "../lib/api/service.js";

  const namen = { search: "Such-Browser", session: "Sitzungs-Browser" };

  let ansichten = $state([]);
  let bilder = $state({});
  let offen = $state("");
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
      ansichten = (await ladeAnsichten()).views;
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

  async function bild(ansicht) {
    if (offen === ansicht.view) {
      offen = "";
      return;
    }
    offen = ansicht.view;
    if (bilder[ansicht.view] || !ansicht.has_screenshot) return;
    try {
      bilder[ansicht.view] = await requestBlobUrl(
        `/atlas/${ansicht.scope}/${ansicht.view}/screenshot`
      );
    } catch (e) {
      fehler = String(e.message ?? e);
    }
  }

  const kopie = (ansicht) =>
    fuehreAus("kopie", async () => {
      const ergebnis = await oeffneKopie("search", ansicht.view, ansicht.scope);
      meldung =
        "Kopie im Such-Browser geöffnet (ohne Skript, ohne Netz). " +
        "Der Auswahlmodus arbeitet dort wie auf der echten Seite. " +
        ergebnis.file;
    });

  const frei = () =>
    fuehreAus("frei", async () => {
      await gibNetzFrei("search");
      meldung = "Der Such-Browser darf wieder ins Netz.";
    });
</script>

<div class="seite">
  <section>
    <h2>Gesehene Ansichten</h2>
    <p class="hinweis">
      Jede Ansicht wird über ihre Struktur erkannt, nicht über ihren Text. Eine neue Ansicht wird
      einmal mit Kopie, Bild, Adresse und Zeitpunkt gesichert, eine bekannte erhöht nur den Zähler.
    </p>
    <div class="knoepfe">
      <button onclick={() => fuehreAus("merken", () => merkeAnsicht("search"))} disabled={beschaeftigt === "merken"}>
        Aktuelle Ansicht (Such-Browser) merken
      </button>
      <button onclick={() => fuehreAus("merken", () => merkeAnsicht("session"))} disabled={beschaeftigt === "merken"}>
        Aktuelle Ansicht (Sitzungs-Browser) merken
      </button>
      <button onclick={frei} disabled={beschaeftigt === "frei"}>Netzsperre aufheben</button>
    </div>
    {#if meldung}<p class="ok">{meldung}</p>{/if}
    {#if fehler}<p class="bad">{fehler}</p>{/if}
  </section>

  {#if !ansichten.length}
    <p class="hinweis">Noch keine Ansicht aufgezeichnet.</p>
  {/if}

  {#each ansichten as a (a.scope + a.view)}
    <section class="karte">
      <div class="zeile">
        <strong>{namen[a.scope] ?? a.scope}</strong>
        <code class="muted">{a.view}</code>
        <span class="muted">{a.count}× gesehen</span>
        <span class="muted">{a.elements} Elemente</span>
        <span class="fueller"></span>
        <button onclick={() => bild(a)} disabled={!a.has_screenshot}>
          {offen === a.view ? "Bild zu" : "Bild"}
        </button>
        <button onclick={() => kopie(a)} disabled={!a.has_snapshot || beschaeftigt === "kopie"}>
          Kopie im Picker öffnen
        </button>
        <button onclick={() => fuehreAus("vergessen", () => vergissAnsicht(a.scope, a.view))}>
          vergessen
        </button>
      </div>
      <p class="hinweis">
        zuerst {a.first_seen} · zuletzt {a.last_seen} · erreicht über {(a.arrivals ?? []).join(", ")}
      </p>
      <p class="pfad">{a.url}</p>
      {#if offen === a.view && bilder[a.view]}
        <img src={bilder[a.view]} alt="Bild der Ansicht" />
      {/if}
    </section>
  {/each}
</div>

<style>
  .seite { display: flex; flex-direction: column; gap: 18px; padding-bottom: 40px; }
  section { display: flex; flex-direction: column; gap: 8px; }
  h2 {
    font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--muted); margin: 0; padding-bottom: 6px; border-bottom: 1px solid var(--line);
  }
  .karte { border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; background: var(--panel); }
  .knoepfe { display: flex; gap: 8px; flex-wrap: wrap; }
  .zeile { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; font-size: 13px; }
  .fueller { flex: 1; }
  img { max-width: 100%; border: 1px solid var(--line); border-radius: 6px; }
  code { font-size: 12px; }
  .hinweis { font-size: 12px; color: var(--muted); margin: 0; }
  .pfad { font-size: 11px; color: var(--muted); word-break: break-all; margin: 0; }
  .muted { color: var(--muted); }
  .ok { color: var(--ok); font-size: 13px; margin: 0; }
  .bad { color: var(--bad); font-size: 13px; margin: 0; }
</style>
