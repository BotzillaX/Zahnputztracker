<script>
  // Wartet eine Freigabe, haelt der ganze Ablauf an. Deshalb steht dieser
  // Streifen ueber allen Reitern und nicht in einer einzelnen Ansicht.
  import { onMount } from "svelte";
  import { beantworteFreigabe, ladeFreigabe } from "../api/service.js";
  import { events } from "../stores/service.js";

  let anfrage = $state(null);
  let fehler = $state("");
  let beschaeftigt = $state(false);
  let letztesEreignis = $state(0);

  const bezeichnung = { freigabe: "Freigabe nötig", manuell: "Von Hand erledigen" };

  onMount(() => {
    laden();
    const takt = setInterval(laden, 3000);
    return () => clearInterval(takt);
  });

  // Der Livestrom meldet eine neue Anfrage sofort, das Nachladen ist nur
  // der Rueckfall, falls der Strom gerade neu aufgebaut wird.
  $effect(() => {
    const neuestes = $events[0];
    if (!neuestes || neuestes.seq === letztesEreignis) return;
    letztesEreignis = neuestes.seq;
    if (["approval_open", "approval_closed", "approval_cancelled"].includes(neuestes.kind)) {
      laden();
    }
  });

  async function laden() {
    try {
      anfrage = (await ladeFreigabe()).request;
    } catch (e) {
      fehler = String(e.message ?? e);
    }
  }

  async function antworten(entscheidung) {
    if (!anfrage) return;
    beschaeftigt = true;
    fehler = "";
    try {
      await beantworteFreigabe(anfrage.id, entscheidung);
      anfrage = null;
    } catch (e) {
      fehler = String(e.message ?? e);
    } finally {
      beschaeftigt = false;
    }
  }
</script>

{#if anfrage}
  <div class="streifen">
    <div class="text">
      <strong>{bezeichnung[anfrage.mode] ?? anfrage.mode}</strong>
      <span>{anfrage.description}</span>
      <span class="muted">Zustand: {anfrage.state_label}</span>
    </div>
    <div class="knoepfe">
      {#if anfrage.mode === "manuell"}
        <button disabled={beschaeftigt} onclick={() => antworten("erledigt")}>
          Habe ich erledigt
        </button>
        <button disabled={beschaeftigt} onclick={() => antworten("abgelehnt")}>Abbrechen</button>
      {:else}
        <button disabled={beschaeftigt} onclick={() => antworten("erlaubt")}>Erlauben</button>
        <button disabled={beschaeftigt} onclick={() => antworten("abgelehnt")}>Ablehnen</button>
      {/if}
    </div>
  </div>
  {#if fehler}<p class="fehler">{fehler}</p>{/if}
{/if}

<style>
  .streifen {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding: 10px 14px;
    margin-bottom: 16px;
    border: 1px solid var(--warn);
    border-radius: 6px;
    background: var(--panel);
  }
  .text { display: flex; flex-direction: column; gap: 2px; font-size: 13px; }
  .knoepfe { display: flex; gap: 8px; white-space: nowrap; }
  .muted { color: var(--muted); font-size: 12px; }
  .fehler { color: var(--bad); font-size: 13px; }
</style>
