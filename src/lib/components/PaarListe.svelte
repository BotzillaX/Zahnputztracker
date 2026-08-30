<script>
  // Freie Liste aus Paaren. Die Spalten kommen von aussen, damit dieselbe
  // Liste sowohl fuer persoenliche Werte als auch fuer Antwort-Paare passt.
  let { eintraege = $bindable([]), spalten, hinzufuegenText = "Zeile hinzufügen" } = $props();

  function hinzufuegen() {
    const leer = {};
    for (const spalte of spalten) leer[spalte.key] = "";
    eintraege = [...eintraege, leer];
  }

  function entfernen(index) {
    eintraege = eintraege.filter((_, i) => i !== index);
  }
</script>

<div class="liste">
  <div class="kopf" style:grid-template-columns={`repeat(${spalten.length}, 1fr) auto`}>
    {#each spalten as spalte}<span>{spalte.label}</span>{/each}
    <span></span>
  </div>
  {#each eintraege as eintrag, index}
    <div class="zeile" style:grid-template-columns={`repeat(${spalten.length}, 1fr) auto`}>
      {#each spalten as spalte}
        <input bind:value={eintrag[spalte.key]} placeholder={spalte.platzhalter ?? ""} />
      {/each}
      <button type="button" class="weg" onclick={() => entfernen(index)} title="Zeile entfernen">
        ×
      </button>
    </div>
  {/each}
  {#if eintraege.length === 0}
    <p class="leer">Noch keine Einträge.</p>
  {/if}
  <button type="button" onclick={hinzufuegen}>{hinzufuegenText}</button>
</div>

<style>
  .liste { display: flex; flex-direction: column; gap: 6px; }
  .kopf, .zeile { display: grid; gap: 6px; align-items: center; }
  .kopf { font-size: 11px; color: var(--muted); }
  .weg { padding: 4px 10px; line-height: 1; }
  .leer { color: var(--muted); font-size: 13px; margin: 4px 0; }
</style>
