<script>
  import { onMount } from "svelte";
  import { events } from "../lib/stores/service.js";
  import {
    gehZu,
    ladeBrowser,
    ladeBrowserProgramm,
    setzePause,
    setzeSichtbar,
    starteBrowser,
    stoppeBrowser,
    zaehleFenster
  } from "../lib/api/service.js";

  let zustand = $state(null);
  let fehler = $state("");
  let beschaeftigt = $state("");
  let fensterzahl = $state({});

  const fortschritt = $derived(
    $events.find((e) => e.kind === "browser_download") ?? null
  );

  onMount(() => {
    aktualisieren();
    const takt = setInterval(aktualisieren, 2000);
    return () => clearInterval(takt);
  });

  async function aktualisieren() {
    try {
      zustand = await ladeBrowser();
      for (const instanz of zustand.instances) {
        fensterzahl[instanz.role] = instanz.pids?.length ? await zaehleFenster(instanz.pids) : 0;
      }
    } catch (e) {
      fehler = String(e.message ?? e);
    }
  }

  async function fuehreAus(name, aufgabe) {
    fehler = "";
    beschaeftigt = name;
    try {
      const ergebnis = await aufgabe();
      if (ergebnis && ergebnis.instances) zustand = ergebnis;
      await aktualisieren();
    } catch (e) {
      fehler = String(e.message ?? e);
    } finally {
      beschaeftigt = "";
    }
  }

  function prozent(e) {
    if (!e || !e.total) return null;
    return Math.round((e.done / e.total) * 100);
  }

  function mb(zahl) {
    return (zahl / 1024 / 1024).toFixed(0);
  }
</script>

{#if !zustand}
  <p class="muted">Browser-Zustand wird geladen …</p>
{:else}
  <div class="seite">
    <section>
      <h2>Programm</h2>
      {#if zustand.binary.installed}
        <p class="zeile">
          <span class="ok">geladen</span>
          <span class="muted">Fassung {zustand.binary.version || "unbekannt"}</span>
        </p>
        <p class="pfad">{zustand.binary.directory}</p>
      {:else}
        <p class="zeile"><span class="bad">nicht geladen</span></p>
        <p class="hinweis">
          Wird einmalig von der offiziellen Quelle geladen (mehrere hundert MB) und liegt danach
          unter {zustand.binary.directory}.
        </p>
        <button
          onclick={() => fuehreAus("laden", ladeBrowserProgramm)}
          disabled={zustand.downloading || beschaeftigt === "laden"}
        >
          Programm laden
        </button>
      {/if}

      {#if fortschritt && fortschritt.phase !== "fertig"}
        <div class="balken">
          <div
            class="fuellung"
            class:unbestimmt={prozent(fortschritt) === null}
            style:width={prozent(fortschritt) === null ? "100%" : `${prozent(fortschritt)}%`}
          ></div>
        </div>
        <p class="hinweis">
          {#if fortschritt.phase === "fehler"}
            <span class="bad">Fehlgeschlagen: {fortschritt.message}</span>
          {:else if prozent(fortschritt) !== null}
            {fortschritt.phase}: {prozent(fortschritt)} % ({mb(fortschritt.done)} von
            {mb(fortschritt.total)} MB)
          {:else}
            {fortschritt.phase}: {mb(fortschritt.done ?? 0)} MB
          {/if}
        </p>
      {/if}
    </section>

    <section>
      <h2>Betrieb</h2>
      <div class="knoepfe">
        <button
          onclick={() => fuehreAus("start", starteBrowser)}
          disabled={!zustand.binary.installed || zustand.running || beschaeftigt === "start"}
        >
          {beschaeftigt === "start" ? "startet …" : "Browser starten"}
        </button>
        <button
          onclick={() => fuehreAus("stop", stoppeBrowser)}
          disabled={!zustand.running || beschaeftigt === "stop"}
        >
          Browser schließen
        </button>
        <button
          onclick={() => fuehreAus("pause", () => setzePause(!zustand.paused))}
          disabled={!zustand.running}
        >
          {zustand.paused ? "Fortsetzen" : "Anhalten"}
        </button>
      </div>
      {#if zustand.paused}
        <p class="hinweis">
          Angehalten. Beide Browser bleiben offen und behalten ihren Zustand.
        </p>
      {/if}
    </section>

    {#each zustand.instances as instanz (instanz.role)}
      <section>
        <h2>{instanz.label}</h2>
        <div class="raster">
          <div><span class="muted">Zustand</span><strong>{instanz.running ? "läuft" : "aus"}</strong></div>
          <div><span class="muted">Prozess</span><strong>{instanz.pid ?? "–"}</strong></div>
          <div><span class="muted">Tabs</span><strong>{instanz.tabs}</strong></div>
          <div>
            <span class="muted">Fenster sichtbar</span>
            <strong>{fensterzahl[instanz.role] ?? 0}</strong>
          </div>
          <div>
            <span class="muted">Zusätzliche Seiten geschlossen</span>
            <strong>{instanz.extra_pages_closed}</strong>
          </div>
        </div>
        <p class="pfad">{instanz.url || "keine Adresse"}</p>
        <div class="knoepfe">
          <button
            onclick={() => fuehreAus("sicht", () => setzeSichtbar(instanz.role, !instanz.visible))}
            disabled={!instanz.running}
          >
            {instanz.visible ? "Ausblenden" : "Einblenden"}
          </button>
          <button
            onclick={() => fuehreAus("gehe", () => gehZu(instanz.role))}
            disabled={!instanz.running || beschaeftigt === "gehe"}
          >
            Zur hinterlegten Adresse
          </button>
        </div>
        {#if instanz.last_error}<p class="bad">{instanz.last_error}</p>{/if}
      </section>
    {/each}

    {#if fehler}<p class="bad">{fehler}</p>{/if}
  </div>
{/if}

<style>
  .seite { display: flex; flex-direction: column; gap: 24px; padding-bottom: 40px; }
  section { display: flex; flex-direction: column; gap: 10px; }
  h2 {
    font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--muted); margin: 0; padding-bottom: 6px; border-bottom: 1px solid var(--line);
  }
  .knoepfe { display: flex; gap: 8px; flex-wrap: wrap; }
  .raster { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px; }
  .raster div {
    display: flex; flex-direction: column; gap: 2px; padding: 8px 10px;
    background: var(--panel); border: 1px solid var(--line); border-radius: 6px;
  }
  .raster span { font-size: 11px; }
  .zeile { display: flex; gap: 10px; align-items: center; margin: 0; font-size: 13px; }
  .pfad { font-size: 11px; color: var(--muted); word-break: break-all; margin: 0; }
  .hinweis { font-size: 12px; color: var(--muted); margin: 0; }
  .balken {
    height: 8px; background: var(--panel); border: 1px solid var(--line);
    border-radius: 4px; overflow: hidden;
  }
  .fuellung { height: 100%; background: var(--ok); transition: width 0.2s linear; }
  .fuellung.unbestimmt { opacity: 0.4; }
  .muted { color: var(--muted); }
  .ok { color: var(--ok); }
  .bad { color: var(--bad); font-size: 13px; }
</style>
