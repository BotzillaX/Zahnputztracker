<script>
  import { onMount } from "svelte";
  import { health, sendPing, restartService, ladeEintraege } from "../lib/api/service.js";
  import { events } from "../lib/stores/service.js";

  let letzteAntwort = $state(null);
  let bestand = $state(null);
  let fehler = $state("");

  onMount(() => {
    aktualisieren();
  });

  async function aktualisieren() {
    fehler = "";
    try {
      bestand = await ladeEintraege();
    } catch (e) {
      fehler = String(e.message ?? e);
    }
  }

  async function pruefen() {
    fehler = "";
    try {
      letzteAntwort = await health();
    } catch (e) {
      fehler = String(e.message ?? e);
    }
  }

  async function testereignis() {
    fehler = "";
    try {
      await sendPing();
    } catch (e) {
      fehler = String(e.message ?? e);
    }
  }

  async function neustart() {
    fehler = "";
    try {
      await restartService();
    } catch (e) {
      fehler = String(e.message ?? e);
    }
  }
</script>

<div class="seite">
  <section class="knoepfe">
    <button onclick={pruefen}>Zustand abfragen</button>
    <button onclick={testereignis}>Testereignis senden</button>
    <button onclick={neustart}>Dienst neu starten</button>
    <button onclick={aktualisieren}>Bestand aktualisieren</button>
  </section>

  {#if fehler}<p class="fehler">{fehler}</p>{/if}
  {#if letzteAntwort}<pre>{JSON.stringify(letzteAntwort, null, 2)}</pre>{/if}

  {#if bestand}
    <section>
      <h2>Bestand</h2>
      <div class="zaehler">
        {#each Object.entries(bestand.counts) as [status, anzahl]}
          <div class="karte"><strong>{anzahl}</strong><span>{status}</span></div>
        {/each}
      </div>
    </section>
  {/if}

  <section>
    <h2>Ereignisse</h2>
    {#if $events.length === 0}
      <p class="muted">Noch keine Ereignisse.</p>
    {:else}
      <ul>
        {#each $events as event (event.seq)}
          <li><span class="muted">{event.ts?.slice(11, 23)}</span> <strong>{event.kind}</strong></li>
        {/each}
      </ul>
    {/if}
  </section>
</div>

<style>
  .seite { display: flex; flex-direction: column; gap: 24px; }
  h2 {
    font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--muted); margin: 0 0 8px; padding-bottom: 6px; border-bottom: 1px solid var(--line);
  }
  .knoepfe { display: flex; gap: 8px; flex-wrap: wrap; }
  .zaehler { display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 8px; }
  .karte {
    display: flex; flex-direction: column; gap: 2px; padding: 10px 12px;
    background: var(--panel); border: 1px solid var(--line); border-radius: 6px;
  }
  .karte strong { font-size: 20px; }
  .karte span { font-size: 12px; color: var(--muted); }
  .muted { color: var(--muted); }
  .fehler { color: var(--bad); font-size: 13px; }
  pre {
    background: var(--panel); border: 1px solid var(--line); border-radius: 6px;
    padding: 12px; font-size: 12px; overflow-x: auto;
  }
  ul { list-style: none; padding: 0; font-size: 13px; margin: 0; }
  li { padding: 4px 0; border-bottom: 1px solid var(--line); }
</style>
