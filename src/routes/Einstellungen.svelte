<script>
  import { onMount } from "svelte";
  import Feld from "../lib/components/Feld.svelte";
  import PaarListe from "../lib/components/PaarListe.svelte";
  import Geheimnis from "../lib/components/Geheimnis.svelte";
  import Programm from "../lib/components/Programm.svelte";
  import {
    ladeEinstellungen,
    speichereEinstellungen,
    ladeGeheimnisse,
    ladeTexthilfe
  } from "../lib/api/service.js";

  let daten = $state(null);
  let geheimnisse = $state([]);
  let fehler = $state("");
  let meldung = $state("");
  let laedt = $state(true);
  let platzhalter = $state([]);

  onMount(async () => {
    try {
      daten = await ladeEinstellungen();
      geheimnisse = await ladeGeheimnisse();
      platzhalter = (await ladeTexthilfe()).placeholders;
    } catch (e) {
      fehler = String(e.message ?? e);
    } finally {
      laedt = false;
    }
  });

  async function geheimnisseNeu() {
    geheimnisse = await ladeGeheimnisse();
  }

  function stand(name) {
    return geheimnisse.find((g) => g.name === name)?.present ?? false;
  }

  async function speichern() {
    fehler = "";
    meldung = "";
    try {
      daten = await speichereEinstellungen(daten);
      meldung = "Gespeichert.";
      setTimeout(() => (meldung = ""), 3000);
    } catch (e) {
      fehler = String(e.message ?? e);
    }
  }
</script>

{#if laedt}
  <p class="muted">Einstellungen werden geladen …</p>
{:else if !daten}
  <p class="fehler">{fehler || "Einstellungen nicht verfügbar."}</p>
{:else}
  <div class="seite">
    <Programm />

    <section>
      <h2>Zugang</h2>
      <div class="raster">
        <Feld label="E-Mail">
          <input bind:value={daten.account.email} autocomplete="off" />
        </Feld>
        <div class="voll">
          <Geheimnis
            name="account-password"
            label="Passwort"
            present={stand("account-password")}
            onchange={geheimnisseNeu}
          />
        </div>
      </div>
      <p class="hinweis">
        Passwort und Schlüssel liegen im Windows-Anmeldeinformationsspeicher und werden nie
        zurückgelesen.
      </p>
    </section>

    <section>
      <h2>Quelle</h2>
      <div class="raster">
        <Feld label="Adresse der Ergebnisseite" breit hinweis="Enthält bereits alle Filter.">
          <input bind:value={daten.source.url} spellcheck="false" />
        </Feld>
        <Feld
          label="Adressvorlage für Einzelseiten"
          breit
          hinweis="Platzhalter für die Kennung, zum Beispiel .../{'{'}kennung{'}'}"
        >
          <input bind:value={daten.source.item_url_template} spellcheck="false" />
        </Feld>
        <Feld label="Wartezeit Minimum (s)">
          <input type="number" min="1" max="3600" bind:value={daten.source.reload_min_s} />
        </Feld>
        <Feld label="Wartezeit Maximum (s)">
          <input type="number" min="1" max="3600" bind:value={daten.source.reload_max_s} />
        </Feld>
        <Feld label="Verhaltens-Simulation">
          <label class="schalter">
            <input type="checkbox" bind:checked={daten.source.idle_behavior} />
            <span>zwischen den Aufrufen aktiv</span>
          </label>
        </Feld>
      </div>
    </section>

    <section>
      <h2>Fenster</h2>
      <div class="raster">
        <Feld label="Suche: Breite">
          <input type="number" bind:value={daten.browsers.search.width} />
        </Feld>
        <Feld label="Suche: Höhe">
          <input type="number" bind:value={daten.browsers.search.height} />
        </Feld>
        <Feld label="Sitzung: Breite">
          <input type="number" bind:value={daten.browsers.session.width} />
        </Feld>
        <Feld label="Sitzung: Höhe">
          <input type="number" bind:value={daten.browsers.session.height} />
        </Feld>
      </div>
    </section>

    <section>
      <h2>Textgenerierung</h2>
      <div class="raster">
        <Feld label="Anbieter">
          <select bind:value={daten.composer.provider}>
            <option value="anthropic">Anthropic</option>
          </select>
        </Feld>
        <Feld label="Modell">
          <input bind:value={daten.composer.model} spellcheck="false" />
        </Feld>
        <Feld label="Endpunkt" breit>
          <input bind:value={daten.composer.endpoint} spellcheck="false" />
        </Feld>
        <Feld label="Zeitlimit (s)">
          <input type="number" min="5" max="600" bind:value={daten.composer.timeout_s} />
        </Feld>
        <div class="voll">
          <Geheimnis
            name="composer-api-key"
            label="API-Schlüssel"
            present={stand("composer-api-key")}
            onchange={geheimnisseNeu}
          />
        </div>
        <Feld
          label="Vorlage für den Text"
          breit
          hinweis="Ein unbekannter Platzhalter hält den Vorgang an, statt in Klammern im Text zu landen."
        >
          <textarea rows="6" bind:value={daten.composer.prompt}></textarea>
          <ul class="platzhalter">
            {#each platzhalter as p}
              <li><code>{p.name}</code> {p.meaning}</li>
            {/each}
          </ul>
        </Feld>
      </div>
    </section>

    <section>
      <h2>Persönliche Werte</h2>
      <PaarListe
        bind:eintraege={daten.profile_values}
        spalten={[
          { key: "label", label: "Bezeichnung", platzhalter: "Beruf" },
          { key: "value", label: "Wert", platzhalter: "Selbstständig" }
        ]}
        hinzufuegenText="Wert hinzufügen"
      />
    </section>

    <section>
      <h2>Antwort-Paare für Formularfelder</h2>
      <PaarListe
        bind:eintraege={daten.answers}
        spalten={[
          { key: "label", label: "Bezeichnung", platzhalter: "Haustiere" },
          { key: "value", label: "Interner Wert", platzhalter: "FALSE" },
          { key: "display", label: "Anzeigetext", platzhalter: "Nein" }
        ]}
        hinzufuegenText="Antwort hinzufügen"
      />
    </section>

    <section>
      <h2>Betrieb</h2>
      <div class="raster">
        <Feld label="Testmodus" hinweis="Jeder Versand wird vorgelegt.">
          <label class="schalter">
            <input type="checkbox" bind:checked={daten.review_mode} />
            <span>aktiv</span>
          </label>
        </Feld>
        <Feld label="Signalton bei Fund">
          <label class="schalter">
            <input type="checkbox" bind:checked={daten.sound_on_new} />
            <span>aktiv</span>
          </label>
        </Feld>
        <Feld label="Systembenachrichtigungen">
          <label class="schalter">
            <input type="checkbox" bind:checked={daten.notify} />
            <span>aktiv</span>
          </label>
        </Feld>
        <Feld label="Bestätigungs-Wartezeit (s)">
          <input type="number" step="0.5" min="0.5" max="60" bind:value={daten.confirm_wait_s} />
        </Feld>
        <Feld label="Speicherobergrenze (MB)">
          <input type="number" min="50" bind:value={daten.storage_cap_mb} />
        </Feld>
        <Feld label="Aufgezeichnete Durchläufe" hinweis="Rückschau bei einem Vorfall.">
          <input type="number" min="0" max="200" bind:value={daten.trace_history} />
        </Feld>
        <Feld label="Bildfolge mitschreiben" hinweis="Bilder der letzten zwei Minuten.">
          <label class="schalter">
            <input type="checkbox" bind:checked={daten.record_frames} />
            <span>aktiv</span>
          </label>
        </Feld>
        <Feld label="Protokoll aufbewahren (Tage)">
          <input type="number" min="1" max="365" bind:value={daten.retention_days_log} />
        </Feld>
        <Feld label="Vorfälle aufbewahren (Tage)">
          <input type="number" min="1" max="365" bind:value={daten.retention_days_incident} />
        </Feld>
      </div>
    </section>

    <section>
      <h2>Zeitlimits je Vorgang (s)</h2>
      <div class="raster limits">
        {#each Object.keys(daten.limits).sort() as name}
          <Feld label={name}>
            <input type="number" min="5" max="1800" bind:value={daten.limits[name]} />
          </Feld>
        {/each}
      </div>
    </section>

    <div class="fuss">
      <button onclick={speichern}>Speichern</button>
      {#if meldung}<span class="ok">{meldung}</span>{/if}
      {#if fehler}<span class="fehler">{fehler}</span>{/if}
    </div>
  </div>
{/if}

<style>
  .platzhalter { list-style: none; padding: 0; margin: 6px 0 0; font-size: 11px; color: var(--muted); }
  .platzhalter code { margin-right: 6px; }
  .seite { display: flex; flex-direction: column; gap: 28px; padding-bottom: 60px; }
  section { display: flex; flex-direction: column; gap: 10px; }
  h2 {
    font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--muted); margin: 0; padding-bottom: 6px; border-bottom: 1px solid var(--line);
  }
  .raster { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
  .limits { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .voll { grid-column: 1 / -1; }
  .schalter { display: flex; align-items: center; gap: 8px; font-size: 13px; }
  .schalter input { width: auto; }
  .hinweis { font-size: 11px; color: var(--muted); margin: 0; }
  .fuss {
    position: sticky; bottom: 0; display: flex; align-items: center; gap: 12px;
    padding: 12px 0; background: var(--bg); border-top: 1px solid var(--line);
  }
  .ok { color: var(--ok); font-size: 13px; }
  .fehler { color: var(--bad); font-size: 13px; }
  .muted { color: var(--muted); }
</style>
