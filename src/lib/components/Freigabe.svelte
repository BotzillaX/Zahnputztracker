<script>
  // Wartet eine Freigabe, haelt der ganze Ablauf an. Deshalb steht dieser
  // Streifen ueber allen Reitern und nicht in einer einzelnen Ansicht.
  import { onMount } from "svelte";
  import { requestBlobUrl } from "../api/client.js";
  import { beantworteFreigabe, ladeFreigabe } from "../api/service.js";
  import { events } from "../stores/service.js";

  let anfrage = $state(null);
  let bild = $state("");
  let eingabe = $state("");
  let fehler = $state("");
  let beschaeftigt = $state(false);
  let letztesEreignis = $state(0);
  let gezeigt = 0;

  const titel = {
    freigabe: "Freigabe nötig",
    manuell: "Von Hand erledigen",
    code: "Code eingeben",
    vorschau: "Anschreiben erzeugen?",
    versand: "Jetzt absenden?"
  };

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
      const stand = await ladeFreigabe();
      anfrage = stand.request;
      if (anfrage && anfrage.id !== gezeigt) {
        gezeigt = anfrage.id;
        eingabe = "";
        bild = "";
        if (anfrage.screenshot) {
          try {
            bild = await requestBlobUrl("/approval/screenshot");
          } catch {
            bild = "";
          }
        }
      }
      if (!anfrage) bild = "";
    } catch (e) {
      fehler = String(e.message ?? e);
    }
  }

  async function antworten(entscheidung) {
    if (!anfrage) return;
    beschaeftigt = true;
    fehler = "";
    try {
      await beantworteFreigabe(anfrage.id, entscheidung, eingabe);
      anfrage = null;
      bild = "";
    } catch (e) {
      fehler = String(e.message ?? e);
    } finally {
      beschaeftigt = false;
    }
  }
</script>

{#if anfrage}
  <div class="streifen">
    <div class="kopf">
      <strong>{titel[anfrage.mode] ?? anfrage.mode}</strong>
      <span>{anfrage.description}</span>
    </div>

    {#if anfrage.url}
      <p class="muted klein">{anfrage.title || anfrage.url}</p>
    {:else if anfrage.state_label}
      <p class="muted klein">Zustand: {anfrage.state_label}</p>
    {/if}

    {#if anfrage.fields?.length}
      <table>
        <tbody>
          {#each anfrage.fields as feld}
            <tr>
              <td>{feld.label}</td>
              <td>
                {#if feld.known}
                  {feld.value}
                {:else}
                  <span class="muted">bleibt leer (keine Antwort zugeordnet)</span>
                {/if}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}

    {#if anfrage.text}
      <pre class="text">{anfrage.text}</pre>
    {/if}

    {#if bild}
      <img src={bild} alt="Bildschirmfoto der Seite" />
    {/if}

    {#if anfrage.wants_text}
      <input
        bind:value={eingabe}
        placeholder="Code"
        autocomplete="off"
        spellcheck="false"
        onkeydown={(e) => e.key === "Enter" && antworten("erlaubt")}
      />
    {/if}

    <div class="knoepfe">
      {#if anfrage.mode === "manuell"}
        <button disabled={beschaeftigt} onclick={() => antworten("erledigt")}>
          Habe ich erledigt
        </button>
        <button disabled={beschaeftigt} onclick={() => antworten("abgelehnt")}>Abbrechen</button>
      {:else if anfrage.mode === "code"}
        <button disabled={beschaeftigt || !eingabe} onclick={() => antworten("erlaubt")}>
          Eintragen
        </button>
        <button disabled={beschaeftigt} onclick={() => antworten("abgelehnt")}>Abbrechen</button>
      {:else}
        <button disabled={beschaeftigt} onclick={() => antworten("erlaubt")}>
          {anfrage.mode === "versand" ? "Absenden" : "Erlauben"}
        </button>
        <button disabled={beschaeftigt} onclick={() => antworten("abgelehnt")}>Ablehnen</button>
      {/if}
    </div>
  </div>
  {#if fehler}<p class="fehler">{fehler}</p>{/if}
{/if}

<style>
  .streifen {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 12px 14px;
    margin-bottom: 16px;
    border: 1px solid var(--warn);
    border-radius: 6px;
    background: var(--panel);
  }
  .kopf { display: flex; align-items: baseline; gap: 10px; font-size: 13px; }
  .knoepfe { display: flex; gap: 8px; }
  .muted { color: var(--muted); }
  .klein { font-size: 12px; margin: 0; word-break: break-all; }
  .fehler { color: var(--bad); font-size: 13px; }
  table { font-size: 12px; border-collapse: collapse; }
  td { padding: 2px 12px 2px 0; vertical-align: top; }
  .text {
    max-height: 220px; overflow: auto; white-space: pre-wrap; font-size: 12px;
    background: var(--bg); border: 1px solid var(--line); border-radius: 6px; padding: 8px;
  }
  img { max-width: 100%; max-height: 260px; object-fit: contain; border: 1px solid var(--line); }
  input { max-width: 200px; }
</style>
