<script>
  import { setzeGeheimnis, loescheGeheimnis } from "../api/service.js";

  // Ein Geheimnis wird nie zurueckgelesen. Angezeigt wird nur, ob eines
  // hinterlegt ist.
  let { name, label, present = false, onchange = () => {} } = $props();

  let wert = $state("");
  let meldung = $state("");
  let fehler = $state("");

  async function speichern() {
    meldung = "";
    fehler = "";
    try {
      await setzeGeheimnis(name, wert);
      wert = "";
      meldung = "hinterlegt";
      onchange();
    } catch (e) {
      fehler = String(e.message ?? e);
    }
  }

  async function entfernen() {
    meldung = "";
    fehler = "";
    try {
      await loescheGeheimnis(name);
      meldung = "entfernt";
      onchange();
    } catch (e) {
      fehler = String(e.message ?? e);
    }
  }
</script>

<div class="geheimnis">
  <span class="beschriftung">
    {label}
    <em class:gesetzt={present}>{present ? "hinterlegt" : "nicht hinterlegt"}</em>
  </span>
  <div class="zeile">
    <input type="password" bind:value={wert} placeholder="neuen Wert eingeben" autocomplete="off" />
    <button type="button" onclick={speichern} disabled={!wert}>Speichern</button>
    <button type="button" onclick={entfernen} disabled={!present}>Entfernen</button>
  </div>
  {#if meldung}<span class="hinweis">{meldung}</span>{/if}
  {#if fehler}<span class="fehler">{fehler}</span>{/if}
</div>

<style>
  .geheimnis { display: flex; flex-direction: column; gap: 4px; }
  .beschriftung { font-size: 12px; color: var(--muted); }
  em { font-style: normal; margin-left: 6px; color: var(--bad); }
  em.gesetzt { color: var(--ok); }
  .zeile { display: grid; grid-template-columns: 1fr auto auto; gap: 6px; }
  .hinweis { font-size: 11px; color: var(--ok); }
  .fehler { font-size: 11px; color: var(--bad); }
</style>
