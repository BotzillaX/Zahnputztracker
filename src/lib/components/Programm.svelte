<script>
  /**
   * Der Update-Knopf (Spezifikation 13.4) und die getrennte
   * Aktualisierung des Browser-Programms (13.6).
   *
   * Vor dem Klick wird nichts heruntergeladen. Ein fehlgeschlagener
   * Hintergrundlauf leuchtet nicht: fehlendes Internet ist nichts, was
   * der Benutzer loesen muesste.
   */
  import { onMount } from "svelte";
  import { events, updateStand } from "../stores/service.js";
  import {
    ladeBrowser,
    ladeBrowserProgramm,
    ladeUpdateLage,
    ladeUpdateStand,
    pruefeUpdate,
    starteUpdate
  } from "../api/service.js";

  let lage = $state(null);
  let browser = $state(null);
  let fehler = $state("");
  let meldung = $state("");
  let beschaeftigt = $state("");

  const bezeichnung = {
    nicht_eingerichtet: "Updates noch nicht eingerichtet",
    aktuell: "Aktuell",
    pruefung: "Wird geprüft …",
    verfuegbar: "Update verfügbar",
    laedt: "Wird geladen …",
    bereit: "Neu starten zum Installieren",
    fehler: "Prüfung fehlgeschlagen"
  };

  const stand = $derived($updateStand ?? {});
  const beschriftung = $derived(
    stand.state === "aktuell"
      ? `Aktuell (v${stand.current})`
      : stand.state === "verfuegbar"
        ? `Update auf v${stand.version}`
        : (bezeichnung[stand.state] ?? stand.state)
  );

  const browserFortschritt = $derived($events.find((e) => e.kind === "browser_download") ?? null);

  onMount(async () => {
    try {
      updateStand.set(await ladeUpdateStand());
      browser = await ladeBrowser();
    } catch (e) {
      fehler = String(e.message ?? e);
    }
  });

  const mb = (zahl) => Math.round(((zahl ?? 0) / 1048576) * 10) / 10;
  const prozent = (getan, gesamt) => (gesamt ? Math.round((getan / gesamt) * 100) : null);

  async function pruefen() {
    fehler = "";
    meldung = "";
    lage = null;
    try {
      await pruefeUpdate();
    } catch (e) {
      fehler = String(e.message ?? e);
    }
  }

  /** Erst fragen, was laeuft, dann fragen, ob es beendet werden darf. */
  async function anklopfen() {
    fehler = "";
    meldung = "";
    try {
      const gefunden = await ladeUpdateLage();
      if (gefunden.browsers_running || gefunden.flow_running) {
        lage = gefunden;
        return;
      }
      await installieren();
    } catch (e) {
      fehler = String(e.message ?? e);
    }
  }

  async function installieren() {
    lage = null;
    try {
      await starteUpdate();
    } catch (e) {
      fehler = String(e.message ?? e);
    }
  }

  async function browserErneuern() {
    fehler = "";
    meldung = "";
    beschaeftigt = "browser";
    try {
      const ergebnis = await ladeBrowserProgramm(true);
      meldung = ergebnis.installed
        ? `Browser-Programm aktualisiert (${ergebnis.version || "Fassung unbekannt"}).`
        : "Es war nichts zu tun.";
      browser = await ladeBrowser();
    } catch (e) {
      fehler = String(e.message ?? e);
    } finally {
      beschaeftigt = "";
    }
  }
</script>

<section>
  <h2>Programm</h2>

  <div class="zeile">
    <button
      class="update"
      class:leuchtet={stand.state === "verfuegbar"}
      class:pulst={stand.state === "pruefung" || stand.state === "laedt"}
      class:gedaempft={stand.state === "fehler" || stand.state === "nicht_eingerichtet"}
      title={stand.detail}
      disabled={stand.state === "pruefung" || stand.state === "laedt" || stand.state === "bereit"}
      onclick={() => (stand.state === "verfuegbar" ? anklopfen() : pruefen())}
    >
      {beschriftung}
    </button>
    <span class="hinweis">
      Fassung v{stand.current}
      {#if stand.checked_at} · zuletzt geprüft {stand.checked_at}{/if}
    </span>
  </div>

  {#if stand.state === "laedt"}
    <div class="balken">
      <div
        class="fuellung"
        class:unbestimmt={prozent(stand.done, stand.total) === null}
        style:width={prozent(stand.done, stand.total) === null
          ? "100%"
          : `${prozent(stand.done, stand.total)}%`}
      ></div>
    </div>
    <p class="hinweis">
      {#if stand.total}
        {prozent(stand.done, stand.total)} % ({mb(stand.done)} von {mb(stand.total)} MB)
      {:else}
        {mb(stand.done)} MB geladen
      {/if}
    </p>
  {/if}

  {#if stand.state === "verfuegbar" && stand.notes}
    <details>
      <summary class="hinweis">Was sich ändert</summary>
      <pre>{stand.notes}</pre>
    </details>
  {/if}

  {#if stand.state === "nicht_eingerichtet"}
    <p class="hinweis">
      In der Programmkonfiguration stehen noch Platzhalter statt Konto und öffentlichem Schlüssel.
      Die Anleitung dazu steht in docs\signatur.md. Ohne gültige Signatur wird ohnehin nichts
      installiert.
    </p>
  {/if}

  {#if lage}
    <div class="rueckfrage">
      <p>
        {#if lage.flow_running}Der Vorgang läuft gerade.{/if}
        {#if lage.browsers_running}
          {lage.flow_running ? " Außerdem sind" : "Es sind"} noch Browser geöffnet.
        {/if}
        Vor der Installation wird der Vorgang angehalten, beide Browser werden geschlossen und der
        Dienst beendet. Einstellungen, Registrierung und Datenbank bleiben unverändert.
      </p>
      <div class="knoepfe">
        <button class="leuchtet" onclick={installieren}>Anhalten und installieren</button>
        <button onclick={() => (lage = null)}>Abbrechen</button>
      </div>
    </div>
  {/if}

  <div class="zeile trenner">
    <button onclick={browserErneuern} disabled={beschaeftigt === "browser"}>
      Browser-Programm prüfen
    </button>
    <span class="hinweis">
      {#if browser?.binary?.installed}
        vorhanden{browser.binary.version ? ` (${browser.binary.version})` : ""}
      {:else}
        noch nicht geladen
      {/if}
      · getrennt vom Programm-Update, ohne Neustart
    </span>
  </div>

  {#if browserFortschritt && browserFortschritt.phase !== "fertig"}
    <p class="hinweis">
      {browserFortschritt.phase}: {mb(browserFortschritt.done ?? 0)} MB
      {#if browserFortschritt.total} von {mb(browserFortschritt.total)} MB{/if}
    </p>
  {/if}

  {#if meldung}<p class="ok">{meldung}</p>{/if}
  {#if fehler}<p class="bad">{fehler}</p>{/if}
</section>

<style>
  section { display: flex; flex-direction: column; gap: 8px; }
  h2 {
    font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--muted); margin: 0; padding-bottom: 6px; border-bottom: 1px solid var(--line);
  }
  .zeile { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  .trenner { margin-top: 6px; padding-top: 10px; border-top: 1px solid var(--line); }
  .knoepfe { display: flex; gap: 8px; }
  .update { min-width: 200px; }
  .leuchtet { border-color: var(--ok); color: var(--text); font-weight: 600; }
  .gedaempft { color: var(--muted); }
  .pulst { animation: puls 1.2s ease-in-out infinite; }
  @keyframes puls { 50% { opacity: 0.45; } }
  .balken { height: 6px; background: var(--line); border-radius: 3px; overflow: hidden; }
  .fuellung { height: 100%; background: var(--ok); transition: width 0.2s linear; }
  .fuellung.unbestimmt { animation: puls 1.2s ease-in-out infinite; }
  .rueckfrage {
    border: 1px solid var(--warn); border-radius: 6px; padding: 10px 12px;
    display: flex; flex-direction: column; gap: 8px; font-size: 13px;
  }
  .rueckfrage p { margin: 0; }
  pre { font-size: 12px; white-space: pre-wrap; margin: 6px 0 0; color: var(--muted); }
  .hinweis { font-size: 12px; color: var(--muted); margin: 0; }
  .ok { color: var(--ok); font-size: 13px; margin: 0; }
  .bad { color: var(--bad); font-size: 13px; margin: 0; }
</style>
