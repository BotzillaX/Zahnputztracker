<script>
  // Zustaende, Bedingungen und Aktionsketten. Alles, was hier steht, kommt
  // vom Dienst: die Rollen, der Aktionskatalog, die Quellen. Diese Ansicht
  // kennt keinen einzigen Wert der Zielseite.
  import { onMount } from "svelte";
  import {
    erkenneZustand,
    freieZustandsKennung,
    fuehreKetteAus,
    ladeVorlagen,
    ladeZustaende,
    loescheVorlage,
    loescheZustand,
    schalteVorlagen,
    speichereZustand,
    stelleVorlagenHer,
    uebernimmVorlage
  } from "../lib/api/service.js";

  const bereiche = [
    { id: "search", label: "Such-Browser" },
    { id: "session", label: "Sitzungs-Browser" }
  ];

  let bereich = $state("search");
  let daten = $state(null);
  let vorlagen = $state(null);
  let entwurf = $state(null);
  let erkennung = $state(null);
  let lauf = $state(null);
  let meldung = $state("");
  let fehler = $state("");
  let beschaeftigt = $state("");

  const rollen = $derived(daten?.roles ?? []);
  const aktionsarten = $derived(Object.entries(daten?.actions ?? {}));

  onMount(laden);

  async function laden() {
    try {
      daten = await ladeZustaende(bereich);
      vorlagen = await ladeVorlagen(bereich);
      fehler = "";
    } catch (e) {
      fehler = String(e.message ?? e);
    }
  }

  async function wechsle(id) {
    bereich = id;
    entwurf = null;
    erkennung = null;
    lauf = null;
    meldung = "";
    await laden();
  }

  async function fuehreAus(name, aufgabe) {
    beschaeftigt = name;
    fehler = "";
    meldung = "";
    try {
      await aufgabe();
    } catch (e) {
      fehler = String(e.message ?? e);
    } finally {
      beschaeftigt = "";
    }
  }

  function bearbeiten(zustand) {
    entwurf = JSON.parse(JSON.stringify(zustand));
  }

  async function neu() {
    const { id } = await freieZustandsKennung(bereich, "zustand");
    entwurf = {
      id,
      label: "Neuer Zustand",
      priority: 100,
      enabled: true,
      notes: "",
      all: [],
      any: [],
      actions: []
    };
  }

  function bedingungHinzu(feld) {
    if (!rollen.length) return;
    entwurf[feld] = [...entwurf[feld], { kind: "sichtbar", role: rollen[0].id }];
  }

  function bedingungWeg(feld, index) {
    entwurf[feld] = entwurf[feld].filter((_, i) => i !== index);
  }

  function aktionHinzu() {
    entwurf.actions = [...entwurf.actions, leereAktion("klicken")];
  }

  function leereAktion(art) {
    const felder = daten.actions[art].fields;
    const aktion = { type: art, mode: "automatisch", notes: "" };
    if (felder.includes("role")) aktion.role = rollen[0]?.id ?? "";
    if (felder.includes("source")) aktion.source = { art: "konfiguration", name: "" };
    if (felder.includes("value")) aktion.value = "";
    if (felder.includes("seconds")) aktion.seconds = 10;
    if (felder.includes("target")) aktion.target = "";
    if (felder.includes("prompt")) aktion.prompt = "";
    if (felder.includes("message")) aktion.message = "";
    if (felder.includes("reason")) aktion.reason = "";
    return aktion;
  }

  function artWechseln(index, art) {
    const alt = entwurf.actions[index];
    const neuAktion = leereAktion(art);
    // Was beide Arten kennen, bleibt erhalten.
    for (const schluessel of Object.keys(neuAktion)) {
      if (schluessel !== "type" && alt[schluessel] !== undefined) {
        neuAktion[schluessel] = alt[schluessel];
      }
    }
    neuAktion.mode = alt.mode;
    entwurf.actions[index] = neuAktion;
  }

  function verschieben(index, richtung) {
    const ziel = index + richtung;
    if (ziel < 0 || ziel >= entwurf.actions.length) return;
    const liste = [...entwurf.actions];
    [liste[index], liste[ziel]] = [liste[ziel], liste[index]];
    entwurf.actions = liste;
  }

  function aktionWeg(index) {
    entwurf.actions = entwurf.actions.filter((_, i) => i !== index);
  }

  function felder(art) {
    return daten?.actions?.[art]?.fields ?? [];
  }

  function quellenNamen(art) {
    if (art === "konfiguration") return daten.config_names;
    if (art === "antwort") return daten.answer_names;
    if (art === "geheimnis") return daten.secret_names.map((e) => e.name);
    return daten.variables.entries.map((e) => e.name);
  }

  const speichern = () =>
    fuehreAus("speichern", async () => {
      await speichereZustand(bereich, entwurf);
      meldung = `Zustand ${entwurf.label} gespeichert`;
      entwurf = null;
      await laden();
    });

  const loeschen = (id) =>
    fuehreAus("loeschen", async () => {
      await loescheZustand(bereich, id);
      if (entwurf?.id === id) entwurf = null;
      await laden();
    });

  const umschalten = (zustand) =>
    fuehreAus("umschalten", async () => {
      await speichereZustand(bereich, { ...zustand, enabled: !zustand.enabled });
      await laden();
    });

  const erkennen = () =>
    fuehreAus("erkennen", async () => {
      erkennung = await erkenneZustand(bereich);
      lauf = null;
    });

  const ausfuehren = () =>
    fuehreAus("ausfuehren", async () => {
      lauf = await fuehreKetteAus(bereich);
      erkennung = null;
      await laden();
    });

  const vorlageLaden = (id) =>
    fuehreAus("vorlage", async () => {
      await uebernimmVorlage(id, bereich);
      meldung = "Vorlage geladen. Sie ist jetzt ein normaler Zustand.";
      await laden();
    });

  const vorlageWeg = (id) => fuehreAus("vorlage", async () => { await loescheVorlage(id); await laden(); });
  const vorlagenSchalter = () =>
    fuehreAus("vorlage", async () => {
      await schalteVorlagen(!vorlagen.enabled);
      await laden();
    });
  const vorlagenZurueck = () => fuehreAus("vorlage", async () => { await stelleVorlagenHer(); await laden(); });
</script>

<div class="kopf">
  {#each bereiche as b}
    <button class:aktiv={bereich === b.id} onclick={() => wechsle(b.id)}>{b.label}</button>
  {/each}
  <span class="fueller"></span>
  <button onclick={erkennen} disabled={beschaeftigt === "erkennen"}>Zustand jetzt erkennen</button>
  <button onclick={ausfuehren} disabled={beschaeftigt === "ausfuehren"}>Kette ausführen</button>
</div>

{#if fehler}<p class="bad">{fehler}</p>{/if}
{#if meldung}<p class="muted">{meldung}</p>{/if}

{#if !daten}
  <p class="muted">Wird geladen …</p>
{:else}
  {#if erkennung}
    <section class="ergebnis">
      <h2>Erkennung</h2>
      {#if erkennung.error}
        <p class="bad">{erkennung.error}</p>
      {:else}
        <p>
          {#if erkennung.chosen}
            Zutreffend: <strong>{erkennung.chosen_label}</strong>
          {:else}
            <span class="bad">Kein Zustand trifft zu</span>
          {/if}
          {#if erkennung.reason}<span class="muted"> ({erkennung.reason})</span>{/if}
        </p>
        <p class="muted">
          {#each Object.entries(erkennung.visible) as [rolle, sichtbar]}
            <span class="marke" class:ja={sichtbar}>{rolle}</span>
          {/each}
        </p>
      {/if}
    </section>
  {/if}

  {#if lauf}
    <section class="ergebnis">
      <h2>Letzter Lauf</h2>
      {#each lauf.rounds as runde, i}
        <p class="muted">Durchgang {i + 1}: {runde.state}</p>
        <ol>
          {#each runde.steps as schritt}
            <li>{schritt.description} <span class="muted">→ {schritt.outcome}</span></li>
          {/each}
        </ol>
      {/each}
      {#if lauf.stopped}<p class="bad">Angehalten: {lauf.stopped}</p>{/if}
    </section>
  {/if}

  <section>
    <div class="zeile">
      <h2>Zustände ({daten.states.length})</h2>
      <button onclick={neu}>Zustand anlegen</button>
    </div>
    {#if daten.states.length === 0}
      <p class="muted">Noch kein Zustand. Ohne Zustand tut die Anwendung nichts.</p>
    {/if}
    {#each [...daten.states].sort((a, b) => a.priority - b.priority) as zustand}
      <div class="karte">
        <div class="zeile">
          <div>
            <strong>{zustand.label}</strong>
            <span class="muted">Priorität {zustand.priority} · {zustand.id}</span>
            {#if !zustand.enabled}<span class="marke">aus</span>{/if}
            {#if zustand.origin}<span class="marke">aus Vorlage</span>{/if}
          </div>
          <div class="knoepfe">
            <button onclick={() => umschalten(zustand)}>
              {zustand.enabled ? "abschalten" : "einschalten"}
            </button>
            <button onclick={() => bearbeiten(zustand)}>bearbeiten</button>
            <button onclick={() => loeschen(zustand.id)}>löschen</button>
          </div>
        </div>
        <p class="muted">
          {zustand.all.length} Bedingung(en){zustand.any.length
            ? ` und eine ODER-Gruppe mit ${zustand.any.length}`
            : ""} · {zustand.actions.length} Aktion(en)
        </p>
      </div>
    {/each}
  </section>

  {#if entwurf}
    <section class="editor">
      <h2>Zustand bearbeiten</h2>
      <div class="raster">
        <label>Kennung<input bind:value={entwurf.id} /></label>
        <label>Anzeigename<input bind:value={entwurf.label} /></label>
        <label>
          Priorität (kleiner ist stärker)
          <input type="number" min="1" max="999" bind:value={entwurf.priority} />
        </label>
        <label class="schalter">
          <input type="checkbox" bind:checked={entwurf.enabled} /> eingeschaltet
        </label>
      </div>
      <label>Notiz<input bind:value={entwurf.notes} /></label>

      {#each [{ feld: "all", titel: "Bedingungen (alle müssen zutreffen)" }, { feld: "any", titel: "ODER-Gruppe (mindestens eine, optional)" }] as gruppe}
        <h3>{gruppe.titel}</h3>
        {#each entwurf[gruppe.feld] as bedingung, index}
          <div class="zeile bedingung">
            <select bind:value={bedingung.role}>
              {#each rollen as r}
                <option value={r.id}>{r.label}{r.taught ? "" : " (nicht angelernt)"}</option>
              {/each}
            </select>
            <select bind:value={bedingung.kind}>
              {#each Object.entries(daten.conditions) as [wert, text]}
                <option value={wert}>{text}</option>
              {/each}
            </select>
            <button onclick={() => bedingungWeg(gruppe.feld, index)}>×</button>
          </div>
        {/each}
        <button onclick={() => bedingungHinzu(gruppe.feld)} disabled={!rollen.length}>
          Bedingung hinzufügen
        </button>
      {/each}

      <h3>Aktionskette</h3>
      {#each entwurf.actions as aktion, index}
        <div class="karte aktion">
          <div class="zeile">
            <select value={aktion.type} onchange={(e) => artWechseln(index, e.target.value)}>
              {#each aktionsarten as [wert, eintrag]}
                <option value={wert}>{eintrag.label}</option>
              {/each}
            </select>
            <select bind:value={aktion.mode}>
              {#each Object.entries(daten.modes) as [wert, text]}
                <option value={wert}>{text}</option>
              {/each}
            </select>
            <div class="knoepfe">
              <button onclick={() => verschieben(index, -1)}>↑</button>
              <button onclick={() => verschieben(index, 1)}>↓</button>
              <button onclick={() => aktionWeg(index)}>×</button>
            </div>
          </div>
          <div class="raster">
            {#if felder(aktion.type).includes("role")}
              <label>
                Rolle
                <select bind:value={aktion.role}>
                  {#each rollen as r}<option value={r.id}>{r.label}</option>{/each}
                </select>
              </label>
            {/if}
            {#if felder(aktion.type).includes("source")}
              <label>
                Quelle
                <select bind:value={aktion.source.art}>
                  {#each Object.entries(daten.sources) as [wert, text]}
                    <option value={wert}>{text}</option>
                  {/each}
                </select>
              </label>
              <label>
                Name
                <input list={`quelle-${index}`} bind:value={aktion.source.name} />
                <datalist id={`quelle-${index}`}>
                  {#each quellenNamen(aktion.source.art) as name}<option value={name}></option>{/each}
                </datalist>
              </label>
            {/if}
            {#if felder(aktion.type).includes("value")}
              <label>
                Wert
                <input list={`werte-${index}`} bind:value={aktion.value} />
                <datalist id={`werte-${index}`}>
                  {#each rollen.find((r) => r.id === aktion.role)?.options ?? [] as o}
                    <option value={o.value}>{o.display}</option>
                  {/each}
                </datalist>
              </label>
            {/if}
            {#if felder(aktion.type).includes("seconds")}
              <label>Sekunden<input type="number" min="1" max="600" bind:value={aktion.seconds} /></label>
            {/if}
            {#if felder(aktion.type).includes("target")}
              <label>Zielvariable<input bind:value={aktion.target} /></label>
            {/if}
            {#if felder(aktion.type).includes("message")}
              <label>Meldung<input bind:value={aktion.message} /></label>
            {/if}
            {#if felder(aktion.type).includes("reason")}
              <label>Grund<input bind:value={aktion.reason} /></label>
            {/if}
            {#if felder(aktion.type).includes("prompt")}
              <label class="breit">Prompt<textarea rows="3" bind:value={aktion.prompt}></textarea></label>
            {/if}
          </div>
        </div>
      {/each}
      <button onclick={aktionHinzu}>Aktion hinzufügen</button>

      <div class="zeile abschluss">
        <button onclick={speichern} disabled={beschaeftigt === "speichern"}>Speichern</button>
        <button onclick={() => (entwurf = null)}>Verwerfen</button>
      </div>
    </section>
  {/if}

  <section>
    <div class="zeile">
      <h2>Vorlagen</h2>
      <div class="knoepfe">
        <button onclick={vorlagenSchalter}>
          {vorlagen?.enabled ? "Vorlagen abschalten" : "Vorlagen einschalten"}
        </button>
        <button onclick={vorlagenZurueck}>Mitgelieferte wiederherstellen</button>
      </div>
    </div>
    {#if !vorlagen?.enabled}
      <p class="muted">Die Vorlagen sind abgeschaltet und werden nicht angeboten.</p>
    {:else if (vorlagen?.templates ?? []).length === 0}
      <p class="muted">Für diese Instanz gibt es keine Vorlage.</p>
    {:else}
      {#each vorlagen.templates as vorlage}
        <div class="karte">
          <div class="zeile">
            <div>
              <strong>{vorlage.label}</strong>
              <span class="muted">{vorlage.description}</span>
            </div>
            <div class="knoepfe">
              <button onclick={() => vorlageLaden(vorlage.id)}>Vorlage laden</button>
              <button onclick={() => vorlageWeg(vorlage.id)}>löschen</button>
            </div>
          </div>
        </div>
      {/each}
    {/if}
    {#if vorlagen?.file}<p class="muted klein">Datei: {vorlagen.file}</p>{/if}
  </section>

  <section>
    <h2>Variablen des laufenden Vorgangs</h2>
    {#if (daten.variables.entries ?? []).length === 0}
      <p class="muted">Der Variablenraum ist leer.</p>
    {:else}
      {#each daten.variables.entries as eintrag}
        <p class="muted">
          <strong>{eintrag.name}</strong> ({eintrag.length} Zeichen): {eintrag.preview}{eintrag.truncated
            ? " …"
            : ""}
        </p>
      {/each}
    {/if}
  </section>
{/if}

<style>
  .kopf { display: flex; align-items: center; gap: 8px; margin-bottom: 14px; }
  .fueller { flex: 1; }
  .kopf button.aktiv { background: var(--panel); border-color: var(--line); }
  section { margin-bottom: 22px; }
  h2 { font-size: 14px; margin: 0 0 8px; }
  h3 { font-size: 13px; margin: 14px 0 6px; color: var(--muted); }
  .zeile { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .zeile.bedingung { justify-content: flex-start; margin-bottom: 6px; }
  .knoepfe { display: flex; gap: 6px; }
  .karte {
    border: 1px solid var(--line); border-radius: 6px; padding: 10px 12px; margin-bottom: 8px;
    background: var(--panel);
  }
  .karte.aktion { background: transparent; }
  .editor { border: 1px solid var(--line); border-radius: 6px; padding: 12px 14px; }
  .raster { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; margin: 8px 0; }
  .raster .breit { grid-column: 1 / -1; }
  label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--muted); }
  label.schalter { flex-direction: row; align-items: center; }
  .abschluss { justify-content: flex-start; margin-top: 12px; }
  .muted { color: var(--muted); font-size: 12px; }
  .klein { font-size: 11px; }
  .bad { color: var(--bad); font-size: 13px; }
  .marke {
    display: inline-block; border: 1px solid var(--line); border-radius: 10px;
    padding: 0 7px; margin-right: 4px; font-size: 11px;
  }
  .marke.ja { border-color: var(--ok); color: var(--ok); }
  ol { margin: 4px 0 10px 18px; font-size: 12px; }
</style>
