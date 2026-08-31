<script>
  import { onMount } from "svelte";
  import { events } from "../lib/stores/service.js";
  import {
    exportiereRegistrierung,
    freieKennung,
    importiereRegistrierung,
    ladePicker,
    ladeRegistrierung,
    ladeVersionen,
    loescheRolle,
    pruefeRollen,
    setzeZurueck,
    speichereRolle,
    startePicker,
    stoppePicker,
    uebernimmGrundkatalog,
    verwirfAuswahl
  } from "../lib/api/service.js";

  const bereiche = [
    { id: "search", label: "Such-Browser" },
    { id: "session", label: "Sitzungs-Browser" }
  ];

  let bereich = $state("search");
  let dokument = $state(null);
  let versionen = $state([]);
  let picker = $state({ active: false, scope: "", pick: null });
  let pruefung = $state(null);
  let meldung = $state("");
  let fehler = $state("");
  let beschaeftigt = $state("");

  // Zuordnungspanel
  let ziel = $state("neu");
  let neueKennung = $state("");
  let neuerName = $state("");
  let menge = $state("einzel");
  let kennungstraeger = $state("");
  let notiz = $state("");
  let behalten = $state([]);

  const auswahl = $derived(picker.pick && picker.pick.scope === bereich ? picker.pick : null);
  const element = $derived(auswahl?.element ?? null);
  const rollen = $derived(dokument?.roles ?? []);
  const letztesEreignis = $derived($events.find((e) => e.kind === "pick") ?? null);

  onMount(() => {
    alles();
    const takt = setInterval(pickerStand, 1500);
    return () => clearInterval(takt);
  });

  $effect(() => {
    // Bei einer neuen Auswahl das Panel frisch vorbereiten.
    if (letztesEreignis) pickerStand();
  });

  async function alles() {
    fehler = "";
    try {
      dokument = await ladeRegistrierung(bereich);
      versionen = (await ladeVersionen(bereich)).versions;
      pruefung = null;
      await pickerStand();
    } catch (e) {
      fehler = String(e.message ?? e);
    }
  }

  async function pickerStand() {
    try {
      const vorher = picker.pick;
      picker = await ladePicker();
      if (picker.pick && picker.pick !== vorher && picker.pick.scope === bereich) {
        await panelVorbereiten();
      }
    } catch (e) {
      /* der Dienst antwortet gleich wieder */
    }
  }

  async function panelVorbereiten() {
    ziel = "neu";
    menge = "einzel";
    notiz = "";
    kennungstraeger = "";
    neuerName = "";
    behalten = (picker.pick?.element?.candidates ?? []).map(() => true);
    try {
      neueKennung = (await freieKennung(bereich, "rolle")).id;
    } catch (e) {
      neueKennung = "rolle";
    }
  }

  function beiWechsel(neuerBereich) {
    bereich = neuerBereich;
    alles();
  }

  async function fuehreAus(name, aufgabe) {
    fehler = "";
    meldung = "";
    beschaeftigt = name;
    try {
      await aufgabe();
    } catch (e) {
      fehler = String(e.message ?? e);
    } finally {
      beschaeftigt = "";
    }
  }

  const pickerAn = () => fuehreAus("picker", async () => {
    await startePicker(bereich);
    await pickerStand();
  });

  const pickerAus = () => fuehreAus("picker", async () => {
    await stoppePicker(bereich);
    await pickerStand();
  });

  const katalog = () => fuehreAus("katalog", async () => {
    dokument = await uebernimmGrundkatalog(bereich);
    versionen = (await ladeVersionen(bereich)).versions;
    meldung = "Grundkatalog ergänzt. Die Rollen sind noch leer und müssen angelernt werden.";
  });

  const pruefen = (rolle) => fuehreAus("pruefen", async () => {
    pruefung = await pruefeRollen(bereich, rolle);
  });

  const exportieren = () => fuehreAus("export", async () => {
    const ergebnis = await exportiereRegistrierung(bereich);
    meldung = `Exportiert nach ${ergebnis.path}`;
  });

  async function importieren(ereignis) {
    const datei = ereignis.target.files?.[0];
    if (!datei) return;
    await fuehreAus("import", async () => {
      const text = await datei.text();
      dokument = await importiereRegistrierung(bereich, JSON.parse(text));
      versionen = (await ladeVersionen(bereich)).versions;
      meldung = `Importiert: ${dokument.roles.length} Rollen`;
    });
    ereignis.target.value = "";
  }

  const zurueck = (version) => fuehreAus("zurueck", async () => {
    dokument = await setzeZurueck(bereich, version);
    versionen = (await ladeVersionen(bereich)).versions;
    meldung = `Auf Fassung ${version} zurückgesetzt.`;
  });

  const entfernen = (id) => fuehreAus("loeschen", async () => {
    dokument = await loescheRolle(bereich, id);
    versionen = (await ladeVersionen(bereich)).versions;
  });

  const verwerfen = () => fuehreAus("verwerfen", async () => {
    picker = await verwirfAuswahl();
  });

  function zuordnen() {
    return fuehreAus("zuordnen", async () => {
      const merkmale = (element?.candidates ?? []).filter((_, i) => behalten[i]);
      if (!merkmale.length) throw new Error("Mindestens ein Merkmal muss bleiben");
      const vorhanden = ziel === "neu" ? null : rollen.find((r) => r.id === ziel);
      const rolle = {
        id: ziel === "neu" ? neueKennung.trim() : ziel,
        label: ziel === "neu" ? neuerName.trim() || neueKennung.trim() : vorhanden.label,
        menge,
        notes: notiz || vorhanden?.notes || "",
        key_attribute: kennungstraeger,
        options: element?.options ?? [],
        candidates: merkmale
      };
      dokument = await speichereRolle(bereich, rolle);
      versionen = (await ladeVersionen(bereich)).versions;
      picker = await verwirfAuswahl();
      meldung = `Rolle ${rolle.id} gespeichert (Fassung ${dokument.version}).`;
    });
  }

  function art(merkmal) {
    return dokument?.kinds?.[merkmal.kind] ?? merkmal.kind;
  }

  function befund(id) {
    return pruefung?.results?.find((r) => r.role === id) ?? null;
  }
</script>

{#if !dokument}
  <p class="muted">Registrierung wird geladen …</p>
{:else}
  <div class="seite">
    <section>
      <div class="kopf">
        <div class="knoepfe">
          {#each bereiche as b}
            <button class:aktiv={bereich === b.id} onclick={() => beiWechsel(b.id)}>{b.label}</button>
          {/each}
        </div>
        <span class="muted">Fassung {dokument.version} · {rollen.length} Rollen</span>
      </div>
      <div class="knoepfe">
        {#if picker.active && picker.scope === bereich}
          <button onclick={pickerAus} disabled={beschaeftigt === "picker"}>Auswahlmodus beenden</button>
        {:else}
          <button onclick={pickerAn} disabled={beschaeftigt === "picker"}>Auswahlmodus starten</button>
        {/if}
        <button onclick={() => pruefen(null)} disabled={beschaeftigt === "pruefen"}>
          Alle Rollen auf der offenen Seite prüfen
        </button>
        <button onclick={katalog} disabled={beschaeftigt === "katalog"}>Grundkatalog ergänzen</button>
        <button onclick={exportieren} disabled={beschaeftigt === "export"}>Exportieren</button>
        <label class="datei">
          Importieren
          <input type="file" accept="application/json" onchange={importieren} />
        </label>
      </div>
      <p class="hinweis">
        Der Auswahlmodus läuft im eingeblendeten Browser-Fenster. Dort wirkt auch Strg+Umschalt+Y.
        Element anfahren, mit den Pfeiltasten die Ebene wechseln, Enter übernimmt.
      </p>
      {#if meldung}<p class="ok">{meldung}</p>{/if}
      {#if fehler}<p class="bad">{fehler}</p>{/if}
    </section>

    {#if element}
      <section class="panel">
        <h2>Auswahl zuordnen</h2>
        <p class="zeile">
          <strong>&lt;{element.tag}&gt;</strong>
          <span class="muted">{element.visible ? "sichtbar" : "nicht sichtbar"}</span>
        </p>
        {#if element.text}<p class="hinweis">Text: {element.text}</p>{/if}
        <p class="pfad">{auswahl.url}</p>

        <div class="reihe">
          <label>
            Rolle
            <select bind:value={ziel}>
              <option value="neu">(neue Rolle anlegen)</option>
              {#each rollen as r}
                <option value={r.id}>{r.label} ({r.id})</option>
              {/each}
            </select>
          </label>
          {#if ziel === "neu"}
            <label>
              Kennung
              <input bind:value={neueKennung} spellcheck="false" />
            </label>
            <label>
              Anzeigename
              <input bind:value={neuerName} placeholder="frei wählbar" />
            </label>
          {/if}
          <label>
            Menge
            <select bind:value={menge}>
              <option value="einzel">einzel</option>
              <option value="liste">liste</option>
            </select>
          </label>
          <label>
            Kennungsträger
            <select bind:value={kennungstraeger}>
              <option value="">(keiner)</option>
              {#each element.attributes as a}
                <option value={a.name}>{a.name}</option>
              {/each}
            </select>
          </label>
        </div>

        <label class="voll">
          Notiz
          <input bind:value={notiz} placeholder="frei" />
        </label>

        <h3>Erkennungsmerkmale, in dieser Reihenfolge geprüft</h3>
        <ul class="merkmale">
          {#each element.candidates as m, i}
            <li>
              <label>
                <input type="checkbox" bind:checked={behalten[i]} />
                <span class="art">{art(m)}</span>
                <code>{m.kind === "attr" ? `${m.attr} = ${m.value}` : m.value}</code>
                {#if m.kind === "aria"}<span class="muted">Rolle {m.role}</span>{/if}
              </label>
            </li>
          {/each}
        </ul>

        {#if element.options.length}
          <h3>Werte des Auswahlfeldes</h3>
          <ul class="werte">
            {#each element.options as o}
              <li><code>{o.value || "(leer)"}</code> <span class="muted">{o.display}</span></li>
            {/each}
          </ul>
        {/if}

        <div class="knoepfe">
          <button onclick={zuordnen} disabled={beschaeftigt === "zuordnen"}>Zuordnen und speichern</button>
          <button onclick={verwerfen}>Auswahl verwerfen</button>
        </div>
      </section>
    {/if}

    <section>
      <h2>Rollen</h2>
      {#if !rollen.length}
        <p class="hinweis">
          Noch nichts angelernt. Die Anwendung kann bewusst nichts tun, solange sie die Seite nicht
          kennt.
        </p>
      {/if}
      {#each rollen as r (r.id)}
        <div class="rolle">
          <div class="zeile">
            <strong>{r.label}</strong>
            <code class="muted">{r.id}</code>
            <span class="muted">{r.menge}</span>
            <span class="muted">{r.candidates.length} Merkmale</span>
            {#if r.key_attribute}<span class="muted">Kennung: {r.key_attribute}</span>{/if}
            {#if befund(r.id)}
              {#if befund(r.id).ambiguous}
                <span class="bad">mehrdeutig</span>
              {:else if befund(r.id).found}
                <span class:warn={befund(r.id).degraded} class:ok={!befund(r.id).degraded}>
                  gefunden über {befund(r.id).kind_label}{befund(r.id).degraded ? " (Degradierung)" : ""}
                </span>
              {:else}
                <span class="muted">nicht gefunden</span>
              {/if}
            {/if}
            <span class="fueller"></span>
            <button onclick={() => pruefen(r.id)}>prüfen</button>
            <button onclick={() => entfernen(r.id)}>löschen</button>
          </div>
          {#if r.notes}<p class="hinweis">{r.notes}</p>{/if}
        </div>
      {/each}
      {#if pruefung}<p class="pfad">geprüft auf {pruefung.url}</p>{/if}
    </section>

    <section>
      <h2>Fassungen</h2>
      {#if !versionen.length}
        <p class="hinweis">Noch keine frühere Fassung.</p>
      {/if}
      {#each versionen as v}
        <div class="zeile">
          <strong>{v.version}</strong>
          <span class="muted">{v.updated}</span>
          <span class="muted">{v.roles} Rollen</span>
          <span class="muted">{v.note}</span>
          <span class="fueller"></span>
          <button onclick={() => zurueck(v.version)}>zurücksetzen</button>
        </div>
      {/each}
    </section>
  </div>
{/if}

<style>
  .seite { display: flex; flex-direction: column; gap: 24px; padding-bottom: 40px; }
  section { display: flex; flex-direction: column; gap: 10px; }
  h2 {
    font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--muted); margin: 0; padding-bottom: 6px; border-bottom: 1px solid var(--line);
  }
  h3 { font-size: 12px; color: var(--muted); margin: 6px 0 0; }
  .kopf { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
  .knoepfe { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  .knoepfe button.aktiv { background: var(--panel); border-color: var(--line); color: var(--text); }
  .panel { border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: var(--panel); }
  .reihe { display: flex; gap: 10px; flex-wrap: wrap; }
  .reihe label, .voll { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--muted); }
  .voll input { width: 100%; }
  .zeile { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin: 0; font-size: 13px; }
  .fueller { flex: 1; }
  .rolle { border-bottom: 1px solid var(--line); padding: 6px 0; }
  .merkmale, .werte { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
  .merkmale label { display: flex; gap: 8px; align-items: center; font-size: 12px; }
  .art { color: var(--muted); min-width: 120px; }
  code { font-size: 12px; word-break: break-all; }
  .datei { font-size: 13px; cursor: pointer; border: 1px solid var(--line); border-radius: 6px; padding: 6px 10px; }
  .datei input { display: none; }
  .hinweis { font-size: 12px; color: var(--muted); margin: 0; }
  .pfad { font-size: 11px; color: var(--muted); word-break: break-all; margin: 0; }
  .muted { color: var(--muted); }
  .ok { color: var(--ok); font-size: 13px; margin: 0; }
  .warn { color: var(--warn); }
  .bad { color: var(--bad); font-size: 13px; margin: 0; }
</style>
