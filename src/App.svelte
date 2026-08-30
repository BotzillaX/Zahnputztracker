<script>
  import { onMount } from "svelte";
  import { initService } from "./lib/api/service.js";
  import { serviceStatus } from "./lib/stores/service.js";
  import Betrieb from "./routes/Betrieb.svelte";
  import Browser from "./routes/Browser.svelte";
  import Einstellungen from "./routes/Einstellungen.svelte";

  const reiter = [
    { id: "betrieb", label: "Betrieb", ansicht: Betrieb },
    { id: "browser", label: "Browser", ansicht: Browser },
    { id: "einstellungen", label: "Einstellungen", ansicht: Einstellungen }
  ];

  let aktiv = $state("betrieb");
  let startfehler = $state("");

  onMount(() => {
    initService().catch((e) => (startfehler = String(e.message ?? e)));
  });

  const farbe = { verbunden: "var(--ok)", startet: "var(--warn)", getrennt: "var(--bad)" };
  const Ansicht = $derived(reiter.find((r) => r.id === aktiv).ansicht);
</script>

<main>
  <header>
    <div class="reiter">
      <h1>Zahnputztracker</h1>
      {#each reiter as r}
        <button class:aktiv={aktiv === r.id} onclick={() => (aktiv = r.id)}>{r.label}</button>
      {/each}
    </div>
    <div class="status">
      <span class="punkt" style:background={farbe[$serviceStatus.state] ?? "var(--muted)"}></span>
      <span>{$serviceStatus.state}</span>
      {#if $serviceStatus.detail}<span class="muted">{$serviceStatus.detail}</span>{/if}
    </div>
  </header>

  {#if startfehler}<p class="fehler">{startfehler}</p>{/if}

  {#if $serviceStatus.state === "verbunden"}
    <Ansicht />
  {:else}
    <p class="muted">Warte auf den Dienst …</p>
  {/if}
</main>

<style>
  main { padding: 20px 24px; max-width: 900px; margin: 0 auto; }
  header {
    display: flex; align-items: center; justify-content: space-between;
    gap: 16px; margin-bottom: 20px;
  }
  .reiter { display: flex; align-items: center; gap: 8px; }
  h1 { font-size: 16px; font-weight: 600; margin: 0 12px 0 0; }
  .reiter button { background: transparent; border-color: transparent; color: var(--muted); }
  .reiter button.aktiv { background: var(--panel); border-color: var(--line); color: var(--text); }
  .status { display: flex; align-items: center; gap: 8px; font-size: 13px; white-space: nowrap; }
  .punkt { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
  .muted { color: var(--muted); }
  .fehler { color: var(--bad); font-size: 13px; }
</style>
