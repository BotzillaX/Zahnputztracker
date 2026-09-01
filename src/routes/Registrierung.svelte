<script>
  import { onMount } from "svelte";
  import {
    exportiereRegistrierung,
    fuegeAuswahlEin,
    importiereRegistrierung,
    ladeAblaufplan,
    ladePicker,
    ladeRegistrierung,
    ladeVersionen,
    loescheRolle,
    pruefeRollen,
    setzeZurueck,
    startePicker,
    stoppePicker,
    vergissAuswahl,
    verwirfAuswahl
  } from "../lib/api/service.js";

  const bereiche = [
    { id: "search", label: "Such-Browser" },
    { id: "session", label: "Sitzungs-Browser" }
  ];

  let bereich = $state("session");
  let plan = $state(null);
  let dokument = $state(null);
  let versionen = $state([]);
  let picker = $state({ active: false, scope: "", picks: [], file: "" });
  let pruefung = $state(null);
  let meldung = $state("");
  let fehler = $state("");
  let beschaeftigt = $state("");

  // Eigener Eintrag
  let eigenerText = $state("");
  let eigeneNotiz = $state("");

  const auswahlen = $derived(picker.picks ?? []);
  const laeuft = $derived(picker.active && picker.scope === bereich);

  onMount(() => {
    alles();
    const takt = setInterval(pickerStand, 1500);
    return () => clearInterval(takt);
  });

  async function alles() {
    fehler = "";
    try {
      plan = await ladeAblaufplan(bereich);
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
      picker = await ladePicker();
    } catch (e) {
      /* der Dienst antwortet gleich wieder */
    }
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

  const pickerAn = () =>
    fuehreAus("picker", async () => {
      await startePicker(bereich);
      await pickerStand();
      meldung =
        "Auswahlmodus läuft. Im Browser-Fenster Element anfahren, Enter übernimmt, Esc beendet.";
    });

  const pickerAus = () =>
    fuehreAus("picker", async () => {
      await stoppePicker(bereich);
      await pickerStand();
    });

  const pruefen = (rolle) =>
    fuehreAus("pruefen", async () => {
      pruefung = await pruefeRollen(bereich, rolle);
    });

  const entfernen = (nummer) =>
    fuehreAus("entfernen", async () => {
      picker = await vergissAuswahl(nummer);
    });

  const alleEntfernen = () =>
    fuehreAus("entfernen", async () => {
      picker = await verwirfAuswahl();
    });

  const eigenenEinfuegen = () =>
    fuehreAus("einfuegen", async () => {
      picker = await fuegeAuswahlEin(eigenerText, eigeneNotiz, bereich);
      eigenerText = "";
      eigeneNotiz = "";
      meldung = "Eingefügt. Sag mir, was es ist.";
    });

  async function kopieren(eintrag) {
    const inhalt = JSON.stringify(eintrag.element ?? eintrag.raw ?? eintrag, null, 1);
    try {
      await navigator.clipboard.writeText(inhalt);
      meldung = "In die Zwischenablage kopiert.";
    } catch (e) {
      fehler = "Kopieren ging nicht. Der Eintrag steht in " + picker.file;
    }
  }

  const exportieren = () =>
    fuehreAus("export", async () => {
      const ergebnis = await exportiereRegistrierung(bereich);
      meldung = `Exportiert nach ${ergebnis.path}`;
    });

  async function importieren(ereignis) {
    const datei = ereignis.target.files?.[0];
    if (!datei) return;
    await fuehreAus("import", async () => {
      const text = await datei.text();
      await importiereRegistrierung(bereich, JSON.parse(text));
      await alles();
      meldung = "Importiert.";
    });
    ereignis.target.value = "";
  }

  const zurueck = (version) =>
    fuehreAus("zurueck", async () => {
      await setzeZurueck(bereich, version);
      await alles();
      meldung = `Auf Fassung ${version} zurückgesetzt.`;
    });

  const rolleLoeschen = (id) =>
    fuehreAus("loeschen", async () => {
      await loescheRolle(bereich, id);
      await alles();
    });

  function beiWechsel(neuerBereich) {
    bereich = neuerBereich;
    alles();
  }

  function befund(id) {
    return pruefung?.results?.find((r) => r.role === id) ?? null;
  }

  function zustand(schritt) {
    if (schritt.taught && !schritt.quantity_ok) return { text: "Menge falsch", klasse: "bad" };
    if (schritt.taught) return { text: "angelernt", klasse: "ok" };
    if (schritt.required) return { text: "fehlt", klasse: "bad" };
    return { text: "optional, nicht angelernt", klasse: "muted" };
  }

  const kurz = (text, laenge = 90) =>
    !text ? "" : text.length > laenge ? text.slice(0, laenge) + " …" : text;
</script>

<div class="seite">
  <section>
    <div class="kopf">
      <div class="knoepfe">
        {#each bereiche as b}
          <button class:aktiv={bereich === b.id} onclick={() => beiWechsel(b.id)}>{b.label}</button>
        {/each}
      </div>
      {#if plan}<span class="muted">Fassung {plan.version}</span>{/if}
    </div>

    <div class="knoepfe">
      {#if laeuft}
        <button class="stark" onclick={pickerAus} disabled={beschaeftigt === "picker"}>
          Auswahlmodus beenden
        </button>
      {:else}
        <button class="stark" onclick={pickerAn} disabled={beschaeftigt === "picker"}>
          Auswahlmodus starten
        </button>
      {/if}
      <button onclick={() => pruefen(null)} disabled={beschaeftigt === "pruefen"}>
        Alle Rollen auf der offenen Seite prüfen
      </button>
    </div>

    <p class="hinweis">
      Der Auswahlmodus läuft im Browser-Fenster, dort wirkt auch Strg+Umschalt+Y. Element anfahren,
      Pfeiltasten wechseln die Ebene, Enter übernimmt. Der Modus bleibt an: du kannst mehrere
      Elemente nacheinander übernehmen. Esc beendet ihn.
    </p>
    {#if meldung}<p class="ok">{meldung}</p>{/if}
    {#if fehler}<p class="bad">{fehler}</p>{/if}
  </section>

  <section>
    <div class="kopf">
      <h2>Ausgewählt ({auswahlen.length})</h2>
      {#if auswahlen.length}
        <button onclick={alleEntfernen} disabled={beschaeftigt === "entfernen"}>
          alle entfernen
        </button>
      {/if}
    </div>

    {#if !auswahlen.length}
      <p class="hinweis">
        Noch nichts ausgewählt. Starte den Auswahlmodus und übernimm im Browser die Elemente, um die
        es geht. Danach sagst du hier, was welches ist.
      </p>
    {/if}

    {#each auswahlen as eintrag, i (eintrag.serial)}
      <div class="karte">
        <div class="zeile">
          <span class="nummer">{i + 1}</span>
          {#if eintrag.element}
            <strong>&lt;{eintrag.element.tag}&gt;</strong>
            <span class="muted">{eintrag.element.visible ? "sichtbar" : "nicht sichtbar"}</span>
            <span class="muted">{eintrag.element.candidates?.length ?? 0} Merkmale</span>
          {:else}
            <strong>von Hand eingefügt</strong>
          {/if}
          <span class="muted">{bereiche.find((b) => b.id === eintrag.scope)?.label ?? ""}</span>
          <span class="muted">{eintrag.at?.slice(11, 19)}</span>
          <span class="fueller"></span>
          <button onclick={() => kopieren(eintrag)}>kopieren</button>
          <button onclick={() => entfernen(eintrag.serial)}>entfernen</button>
        </div>
        {#if eintrag.note}<p class="notiz">{eintrag.note}</p>{/if}
        {#if eintrag.element?.text}<p class="hinweis">Text: {kurz(eintrag.element.text)}</p>{/if}
        {#if eintrag.raw}<p class="pfad">{kurz(eintrag.raw, 200)}</p>{/if}
        {#if eintrag.url}<p class="pfad">{eintrag.url}</p>{/if}
      </div>
    {/each}

    <details>
      <summary>Eigenen Eintrag einfügen</summary>
      <p class="hinweis">
        Für Elemente aus einem anderen Browser: dort im Entwicklerwerkzeug „Element kopieren" wählen
        und hier einfügen.
      </p>
      <textarea rows="4" bind:value={eigenerText} placeholder="HTML einfügen"></textarea>
      <input bind:value={eigeneNotiz} placeholder="Notiz, zum Beispiel: das ist der Anmelden-Knopf" />
      <button
        onclick={eigenenEinfuegen}
        disabled={!eigenerText.trim() || beschaeftigt === "einfuegen"}
      >
        Einfügen
      </button>
    </details>
  </section>

  {#if plan}
    <section>
      <h2>Ablauf und Rollen</h2>
      {#if plan.open.length}
        <p class="bad">Es fehlt noch: {plan.open.join(", ")}</p>
      {:else}
        <p class="ok">Alle Pflichtrollen dieses Browsers sind angelernt.</p>
      {/if}

      {#each plan.groups as gruppe}
        <h3>{gruppe.group}</h3>
        {#each gruppe.steps as schritt}
          <div class="schritt">
            <div class="zeile">
              <span class="nummer">{schritt.position}</span>
              <strong>{schritt.meaning}</strong>
              <code class="muted">{schritt.role}{schritt.family ? "…" : ""}</code>
              <span class={zustand(schritt).klasse}>{zustand(schritt).text}</span>
              {#if schritt.taught && !schritt.family}
                <span class="muted">{schritt.candidates} Merkmale</span>
              {/if}
              {#if !schritt.quantity_ok}
                <span class="bad">
                  Menge ist „{schritt.quantity_is}", nötig ist „{schritt.quantity}"
                </span>
              {/if}
              {#if befund(schritt.role)}
                {#if befund(schritt.role).ambiguous}
                  <span class="bad">mehrdeutig</span>
                {:else if befund(schritt.role).found}
                  <span
                    class:warn={befund(schritt.role).degraded}
                    class:ok={!befund(schritt.role).degraded}
                  >
                    gefunden{befund(schritt.role).degraded ? " (Degradierung)" : ""}
                  </span>
                {:else}
                  <span class="muted">nicht gefunden</span>
                {/if}
              {/if}
            </div>
            <p class="hinweis">{schritt.description}</p>
            {#each schritt.members as m}
              <p class="mitglied">
                <code>{m.role}</code> {m.label}
                {#if m.answer}<span class="muted">Antwort-Paar: {m.answer}</span>{/if}
                <span class="muted">{m.candidates} Merkmale</span>
              </p>
            {/each}
          </div>
        {/each}
      {/each}

      {#if plan.extra.length}
        <h3>Nicht Teil eines Ablaufs</h3>
        <p class="hinweis">Diese Rollen fragt die Anwendung nirgends ab. Sie können weg.</p>
        {#each plan.extra as r}
          <div class="zeile">
            <code>{r.role}</code>
            <span class="muted">{r.label}</span>
            <span class="muted">{r.candidates} Merkmale</span>
            <span class="fueller"></span>
            <button onclick={() => rolleLoeschen(r.role)}>löschen</button>
          </div>
        {/each}
      {/if}
      {#if pruefung}<p class="pfad">geprüft auf {pruefung.url}</p>{/if}
    </section>
  {/if}

  <details class="werkzeuge">
    <summary>Sicherung und Fassungen</summary>
    <div class="knoepfe">
      <button onclick={exportieren} disabled={beschaeftigt === "export"}>Exportieren</button>
      <label class="datei">
        Importieren
        <input type="file" accept="application/json" onchange={importieren} />
      </label>
    </div>
    {#if !versionen.length}<p class="hinweis">Noch keine frühere Fassung.</p>{/if}
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
    {#if dokument?.roles?.length}
      <h3>Alle Rollen</h3>
      {#each dokument.roles as r (r.id)}
        <div class="zeile">
          <code>{r.id}</code>
          <span class="muted">{r.label}</span>
          <span class="muted">{r.menge}</span>
          <span class="muted">{r.candidates.length} Merkmale</span>
          <span class="fueller"></span>
          <button onclick={() => pruefen(r.id)}>prüfen</button>
          <button onclick={() => rolleLoeschen(r.id)}>löschen</button>
        </div>
      {/each}
    {/if}
  </details>
</div>

<style>
  .seite { display: flex; flex-direction: column; gap: 24px; padding-bottom: 40px; }
  section { display: flex; flex-direction: column; gap: 10px; }
  h2 {
    font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--muted); margin: 0; padding-bottom: 6px; border-bottom: 1px solid var(--line);
    flex: 1;
  }
  h3 { font-size: 13px; margin: 10px 0 0; }
  .kopf { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
  .knoepfe { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  .knoepfe button.aktiv { background: var(--panel); border-color: var(--line); color: var(--text); }
  button.stark { border-color: var(--ok); color: var(--text); }
  .karte, .schritt {
    border: 1px solid var(--line); border-radius: 6px; padding: 8px 10px; background: var(--panel);
  }
  .zeile { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin: 0; font-size: 13px; }
  .nummer {
    display: inline-flex; align-items: center; justify-content: center;
    min-width: 20px; height: 20px; border-radius: 10px; background: var(--line);
    font-size: 11px; color: var(--text);
  }
  .fueller { flex: 1; }
  .mitglied { font-size: 12px; margin: 4px 0 0 30px; display: flex; gap: 8px; flex-wrap: wrap; }
  .notiz { font-size: 13px; margin: 4px 0 0; }
  code { font-size: 12px; word-break: break-all; }
  .datei { font-size: 13px; cursor: pointer; border: 1px solid var(--line); border-radius: 6px; padding: 6px 10px; }
  .datei input { display: none; }
  textarea, details input { width: 100%; margin: 6px 0; }
  details { border: 1px solid var(--line); border-radius: 6px; padding: 8px 10px; }
  summary { font-size: 13px; cursor: pointer; color: var(--muted); }
  .werkzeuge { display: flex; flex-direction: column; gap: 8px; }
  .hinweis { font-size: 12px; color: var(--muted); margin: 4px 0 0; }
  .pfad { font-size: 11px; color: var(--muted); word-break: break-all; margin: 2px 0 0; }
  .muted { color: var(--muted); }
  .ok { color: var(--ok); font-size: 13px; margin: 0; }
  .warn { color: var(--warn); }
  .bad { color: var(--bad); font-size: 13px; margin: 0; }
</style>
