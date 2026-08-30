<script>
  import { onMount } from "svelte";
  import { initService, health, sendPing, restartService } from "./lib/api/service.js";
  import { serviceStatus, events } from "./lib/stores/service.js";

  let letzteAntwort = $state(null);
  let fehler = $state("");

  onMount(() => {
    initService().catch((e) => (fehler = String(e)));
  });

  const farbe = { verbunden: "var(--ok)", startet: "var(--warn)", getrennt: "var(--bad)" };

  async function pruefen() {
    fehler = "";
    try {
      letzteAntwort = await health();
    } catch (e) {
      fehler = String(e);
    }
  }

  async function testereignis() {
    fehler = "";
    try {
      await sendPing();
    } catch (e) {
      fehler = String(e);
    }
  }

  async function neustart() {
    fehler = "";
    try {
      await restartService();
    } catch (e) {
      fehler = String(e);
    }
  }
</script>

<main>
  <header>
    <h1>Zahnputztracker</h1>
    <div class="status">
      <span class="punkt" style:background={farbe[$serviceStatus.state] ?? "var(--muted)"}></span>
      <span>{$serviceStatus.state}</span>
      {#if $serviceStatus.detail}<span class="muted">{$serviceStatus.detail}</span>{/if}
    </div>
  </header>

  <section class="knoepfe">
    <button onclick={pruefen}>Zustand abfragen</button>
    <button onclick={testereignis}>Testereignis senden</button>
    <button onclick={neustart}>Dienst neu starten</button>
  </section>

  {#if fehler}<p class="fehler">{fehler}</p>{/if}

  {#if letzteAntwort}
    <pre>{JSON.stringify(letzteAntwort, null, 2)}</pre>
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
</main>

<style>
  main { padding: 24px; max-width: 780px; margin: 0 auto; }
  header { display: flex; align-items: baseline; justify-content: space-between; }
  h1 { font-size: 20px; font-weight: 600; margin: 0 0 16px; }
  h2 { font-size: 14px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); }
  .status { display: flex; align-items: center; gap: 8px; font-size: 13px; }
  .punkt { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
  .knoepfe { display: flex; gap: 8px; margin: 16px 0; flex-wrap: wrap; }
  .muted { color: var(--muted); }
  .fehler { color: var(--bad); font-size: 13px; }
  pre {
    background: var(--panel); border: 1px solid var(--line); border-radius: 6px;
    padding: 12px; font-size: 12px; overflow-x: auto;
  }
  ul { list-style: none; padding: 0; font-size: 13px; }
  li { padding: 4px 0; border-bottom: 1px solid var(--line); }
</style>
