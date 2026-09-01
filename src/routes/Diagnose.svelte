<script>
  import { onMount } from "svelte";
  import { requestBlobUrl } from "../lib/api/client.js";
  import {
    erzeugeBericht,
    halteVorgangAn,
    ladeBerichte,
    ladeDiagnose,
    ladeLaufzeiten,
    ladeVorfaelle,
    ladeVorfall,
    oeffneVorfallImPicker,
    raeumeAuf,
    vergissVorfall
  } from "../lib/api/service.js";

  let diagnose = $state(null);
  let laufzeiten = $state(null);
  let vorfaelle = $state([]);
  let offen = $state(null);
  let bild = $state("");
  let berichte = $state([]);
  let probeName = $state("state.detect");
  let probeSekunden = $state(20);
  let probeBereich = $state("session");
  let meldung = $state("");
  let fehler = $state("");
  let beschaeftigt = $state("");

  const mb = (bytes) => `${Math.round(((bytes ?? 0) / 1048576) * 10) / 10} MB`;
  const sek = (ms) => `${Math.round(((ms ?? 0) / 1000) * 10) / 10} s`;

  onMount(() => {
    laden();
    const takt = setInterval(laden, 3000);
    return () => clearInterval(takt);
  });

  async function laden() {
    try {
      diagnose = await ladeDiagnose();
      vorfaelle = (await ladeVorfaelle()).incidents;
      if (!laufzeiten) laufzeiten = await ladeLaufzeiten();
    } catch (e) {
      fehler = String(e.message ?? e);
    }
  }

  async function fuehreAus(name, aufgabe) {
    beschaeftigt = name;
    fehler = "";
    meldung = "";
    try {
      await aufgabe();
      await laden();
    } catch (e) {
      fehler = String(e.message ?? e);
    } finally {
      beschaeftigt = "";
    }
  }

  async function oeffne(kennung) {
    fehler = "";
    bild = "";
    try {
      offen = await ladeVorfall(kennung);
      if (offen.files?.some((datei) => datei.name === "bild.png")) {
        bild = await requestBlobUrl(`/incidents/${kennung}/file/bild.png`);
      }
    } catch (e) {
      fehler = String(e.message ?? e);
    }
  }

  const probe = () =>
    fuehreAus("probe", async () => {
      const antwort = await halteVorgangAn(probeName, Number(probeSekunden), probeBereich);
      meldung =
        `${antwort.name} wird ${antwort.seconds} s festgehalten. ` +
        `Hartes Limit ${antwort.limit_s} s, weiche Schwelle ` +
        (antwort.soft_ms ? sek(antwort.soft_ms) : "noch keine Referenz") + ".";
    });

  const bericht = () =>
    fuehreAus("bericht", async () => {
      const antwort = await erzeugeBericht("");
      berichte = (await ladeBerichte()).reports;
      meldung = `Bericht ${antwort.name} geschrieben.`;
    });

  const aufraeumen = () =>
    fuehreAus("aufraeumen", async () => {
      const antwort = await raeumeAuf();
      meldung =
        `Gelöscht: ${antwort.incidents.length} Vorfälle, ` +
        `${antwort.traces.length} Aufzeichnungen, ${antwort.logs.length} Protokolltage.`;
    });

  const korrigiere = (stufe) =>
    fuehreAus("korrigieren", async () => {
      const datei = (stufe.folder ? `${stufe.folder}/` : "") + "seite.html";
      const ergebnis = await oeffneVorfallImPicker(offen.incident, "search", datei);
      meldung =
        "Die gespeicherte Seite ist im Such-Browser geöffnet (ohne Skript, ohne Netz). " +
        "Dort den Auswahlmodus starten und die Rolle neu zeigen. " + ergebnis.file;
    });

  const statusfarbe = (stufe) =
    stufe === "blockiert" ? "var(--bad)" : stufe === "auffaellig" ? "var(--warn)" : "var(--ok)";

  const stufenfarbe = (stufe) =>
    stufe === "kritisch" ? "var(--bad)" : stufe === "erhoeht" ? "var(--warn)" : "var(--muted)";
</script>

<div class="seite">
  {#if fehler}<p class="fehler">{fehler}</p>{/if}
  {#if meldung}<p class="muted klein">{meldung}</p>{/if}

  {#if diagnose}
    <section>
      <h2>Zustand</h2>
      <div class="kopf">
        <span class="punkt" style:background={statusfarbe(diagnose.status.level)}></span>
        <strong>{diagnose.status.label}</strong>
        <span class="muted klein">
          {diagnose.status.noticeable} von {diagnose.status.window} Vorgängen auffällig ·
          Wachhund {diagnose.watchdog ? "läuft" : "steht"}
          {#if diagnose.paused} · angehalten (Freigabe offen){/if}
        </span>
      </div>
      {#if diagnose.open.length}
        <table>
          <tbody>
            {#each diagnose.open as vorgang}
              <tr>
                <td>läuft</td>
                <td>{vorgang.name}</td>
                <td>{sek(vorgang.elapsed_ms)} von {vorgang.limit_s} s</td>
                <td class="muted">
                  {vorgang.hard ? "blockiert" : vorgang.soft ? "über der weichen Schwelle" : ""}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </section>

    <section>
      <h2>Zeitleiste</h2>
      {#if diagnose.recent.length === 0}
        <p class="muted klein">Noch nichts gemessen.</p>
      {:else}
        <table>
          <tbody>
            {#each diagnose.recent.slice(0, 25) as vorgang}
              <tr>
                <td class="muted">{vorgang.at?.slice(11, 19)}</td>
                <td>{vorgang.name}</td>
                <td style:color={stufenfarbe(vorgang.level)}>{sek(vorgang.dur_ms)}</td>
                <td class="muted">
                  {vorgang.median_ms ? `üblich ${sek(vorgang.median_ms)}` : "sammelt noch"}
                </td>
                <td class="muted">{vorgang.status}{vorgang.incident ? " · Vorfall" : ""}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </section>

    <section>
      <h2>Speicher</h2>
      <p class="muted klein">
        Aufzeichnungen {mb(diagnose.storage.recordings_bytes)} von {diagnose.storage.cap_mb} MB ·
        Protokoll {mb(diagnose.storage.log_bytes)} · Datenbank {mb(diagnose.storage.database_bytes)}
        · Ansichten {mb(diagnose.storage.views_bytes)}
      </p>
      <div class="knoepfe">
        <button onclick={aufraeumen} disabled={beschaeftigt === "aufraeumen"}>Jetzt aufräumen</button>
        <button onclick={bericht} disabled={beschaeftigt === "bericht"}>Bericht erzeugen</button>
      </div>
      {#if berichte.length}
        <p class="muted klein">Zuletzt: {berichte[0].name}</p>
      {/if}
    </section>

    <section>
      <h2>Vorgang absichtlich festhalten</h2>
      <p class="muted klein">
        Damit lassen sich die beiden Schwellen prüfen, ohne auf einen schlechten Tag der Seite zu
        warten. Der Vorgang bleibt so lange offen, wie hier steht.
      </p>
      <div class="eingabe">
        <select bind:value={probeName}>
          {#each laufzeiten?.names ?? [] as name}<option value={name}>{name}</option>{/each}
        </select>
        <select bind:value={probeBereich}>
          <option value="session">Sitzungs-Browser</option>
          <option value="search">Such-Browser</option>
        </select>
        <input type="number" min="1" max="900" bind:value={probeSekunden} />
        <button onclick={probe} disabled={beschaeftigt === "probe"}>Festhalten</button>
      </div>
    </section>

    <section>
      <h2>Referenzwerte</h2>
      {#if (laufzeiten?.stats ?? []).length === 0}
        <p class="muted klein">Es sind noch keine Laufzeiten gesammelt.</p>
      {:else}
        <table>
          <tbody>
            {#each laufzeiten.stats as zeile}
              <tr>
                <td>{zeile.name}</td>
                <td class="muted">{zeile.scope}</td>
                <td>{zeile.n} Messungen</td>
                <td>üblich {sek(zeile.median_ms)}</td>
                <td class="muted">
                  {zeile.ready
                    ? `auffällig ab ${sek(zeile.elevated_ms)}, kritisch ab ${sek(zeile.critical_ms)}`
                    : `sammelt (ab ${laufzeiten.min_samples} wird bewertet)`}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </section>

    <section>
      <h2>Abgestufte Erkennungsmerkmale</h2>
      {#if diagnose.degraded.length === 0}
        <p class="muted klein">Keine. Jede Rolle wird über ihr bevorzugtes Merkmal gefunden.</p>
      {:else}
        <table>
          <tbody>
            {#each diagnose.degraded as zeile}
              <tr>
                <td>{zeile.label}</td>
                <td class="muted">{zeile.kind_label}</td>
                <td>{zeile.count} mal</td>
                <td class="muted">zuletzt {zeile.last?.slice(11, 19)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </section>
  {/if}

  <section>
    <h2>Vorfälle</h2>
    {#if vorfaelle.length === 0}
      <p class="muted klein">Kein Vorfall aufgezeichnet.</p>
    {:else}
      {#each vorfaelle.slice(0, 20) as vorfall}
        <div class="karte">
          <div class="zeile">
            <div>
              <strong>{vorfall.operation}</strong>
              <span class="muted klein">{vorfall.reason}</span>
            </div>
            <div class="knoepfe">
              <button onclick={() => oeffne(vorfall.incident)}>öffnen</button>
              <button onclick={() => fuehreAus("weg", () => vergissVorfall(vorfall.incident))}>
                vergessen
              </button>
            </div>
          </div>
          <p class="muted klein">
            {vorfall.at?.slice(0, 19).replace("T", " ")} · {vorfall.missing} Rolle(n) nicht gefunden
            · {vorfall.stages} Erfassung(en) · {vorfall.frames} Bilder ·
            {vorfall.traces} Aufzeichnung(en) ·
            {vorfall.reference ? "mit Referenzdurchlauf" : "ohne Referenzdurchlauf"}
            {#if vorfall.span} · {vorfall.span} {sek(vorfall.elapsed_ms)}{/if}
          </p>
        </div>
      {/each}
    {/if}
  </section>

  {#if offen}
    <section>
      <h2>Vorfall {offen.incident}</h2>
      <p class="muted klein">{offen.path}</p>
      {#each offen.stages ?? [] as stufe}
        <div class="karte">
          <strong>{stufe.stage || "Erfassung"}</strong>
          <p class="muted klein">
            {stufe.at?.slice(11, 19)} · {stufe.url || "(keine Adresse)"}
            {#if stufe.viewport} · sichtbar {stufe.viewport.width} x {stufe.viewport.height}{/if}
            {#if stufe.zoom} · Zoom {stufe.zoom}{/if}
            {#if stufe.signed_in !== undefined}
              · {stufe.signed_in ? "angemeldet" : "nicht angemeldet"}
            {/if}
          </p>
          <p class="muted klein">
            gefunden: {(stufe.roles?.found ?? []).map((r) => r.label).join(", ") || "keine"}
          </p>
          <p class="warnung">
            nicht gefunden: {(stufe.roles?.missing ?? []).map((r) => r.label).join(", ") || "keine"}
          </p>
          <div class="knoepfe">
            <button onclick={() => korrigiere(stufe)} disabled={beschaeftigt === "korrigieren"}>
              Im Picker öffnen und korrigieren
            </button>
          </div>
        </div>
      {/each}
      {#if bild}<img src={bild} alt="Bildschirmfoto des Vorfalls" />{/if}
      <details>
        <summary class="muted klein">Dateien im Ordner</summary>
        <ul>
          {#each offen.files ?? [] as datei}
            <li>{datei.name} <span class="muted">({Math.round(datei.bytes / 1024)} kB)</span></li>
          {/each}
        </ul>
      </details>
      <div class="knoepfe">
        <button onclick={() => (offen = null)}>schließen</button>
      </div>
    </section>
  {/if}
</div>

<style>
  .seite { display: flex; flex-direction: column; gap: 24px; }
  h2 {
    font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--muted); margin: 0 0 8px; padding-bottom: 6px; border-bottom: 1px solid var(--line);
  }
  .kopf { display: flex; align-items: center; gap: 10px; font-size: 13px; flex-wrap: wrap; }
  .punkt { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
  .knoepfe { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  .eingabe { display: flex; gap: 8px; align-items: center; }
  .eingabe input { width: 90px; }
  .karte {
    background: var(--panel); border: 1px solid var(--line); border-radius: 6px;
    padding: 8px 10px; margin-bottom: 6px;
  }
  .zeile { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  td { padding: 3px 8px 3px 0; border-bottom: 1px solid var(--line); vertical-align: top; }
  .muted { color: var(--muted); }
  .klein { font-size: 12px; margin: 4px 0 0; }
  .warnung { color: var(--warn); font-size: 12px; margin: 4px 0 0; }
  .fehler { color: var(--bad); font-size: 13px; }
  img { max-width: 100%; max-height: 320px; object-fit: contain; border: 1px solid var(--line); }
  ul { list-style: none; padding: 0; font-size: 12px; margin: 6px 0 0; }
  li { padding: 2px 0; }
</style>
