<script>
  import { onMount } from "svelte";
  import {
    brichVorgangAb,
    entscheideEintrag,
    ladeAblauf,
    ladeAnmeldestand,
    ladeEintraege,
    ladeUnklare,
    ladeVorfaelle,
    restartService,
    starteAnmeldung,
    starteVorgang,
    vergissVorfall
  } from "../lib/api/service.js";
  import { events } from "../lib/stores/service.js";

  let ablauf = $state(null);
  let anmeldung = $state(null);
  let bestand = $state(null);
  let unklar = $state(null);
  let vorfaelle = $state([]);
  let adresse = $state("");
  let titel = $state("");
  let filter = $state("");
  let meldung = $state("");
  let fehler = $state("");
  let beschaeftigt = $state("");

  const fehlend = $derived(ablauf?.readiness?.missing_contact ?? []);

  onMount(() => {
    laden();
    const takt = setInterval(laden, 4000);
    return () => clearInterval(takt);
  });

  async function laden() {
    try {
      ablauf = await ladeAblauf();
      bestand = await ladeEintraege(filter || undefined);
      unklar = await ladeUnklare();
      vorfaelle = (await ladeVorfaelle()).incidents;
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

  const anmeldestand = () =>
    fuehreAus("stand", async () => {
      anmeldung = await ladeAnmeldestand();
    });

  const anmelden = () => fuehreAus("anmelden", starteAnmeldung);
  const abbrechen = () => fuehreAus("abbrechen", brichVorgangAb);

  const vorgangStarten = () =>
    fuehreAus("vorgang", async () => {
      await starteVorgang(adresse.trim(), titel.trim());
      meldung = "Der Vorgang läuft. Freigaben erscheinen oben.";
    });

  const entscheiden = (kennung, entscheidung) =>
    fuehreAus("entscheiden", () => entscheideEintrag(kennung, entscheidung));

  const vorfallWeg = (kennung) => fuehreAus("vorfall", () => vergissVorfall(kennung));

  async function filterWechseln(wert) {
    filter = wert;
    await laden();
  }
</script>

<div class="seite">
  {#if fehler}<p class="fehler">{fehler}</p>{/if}
  {#if meldung}<p class="muted">{meldung}</p>{/if}

  <section>
    <h2>Vorgang</h2>
    {#if ablauf?.busy}
      <p>
        Läuft: <strong>{ablauf.job?.kind}</strong>
        <span class="muted">{ablauf.job?.url ?? ""}</span>
      </p>
      <button onclick={abbrechen} disabled={beschaeftigt === "abbrechen"}>Abbrechen</button>
    {:else}
      <div class="eingabe">
        <input bind:value={adresse} placeholder="Adresse des Eintrags" spellcheck="false" />
        <input bind:value={titel} placeholder="Titel (optional)" />
        <button onclick={vorgangStarten} disabled={!adresse.trim() || beschaeftigt === "vorgang"}>
          Vorgang starten
        </button>
      </div>
      {#if fehlend.length}
        <p class="warnung">Es fehlen noch angelernte Rollen: {fehlend.join(", ")}</p>
      {/if}
      {#if ablauf}
        <p class="muted klein">
          Testmodus {ablauf.review_mode ? "an (es wird zweimal gefragt)" : "aus"}
        </p>
      {/if}
    {/if}

    {#if ablauf?.last}
      <p class="muted klein">
        Zuletzt: {ablauf.last.kind} um {ablauf.last.at?.slice(11, 19)} —
        {#if ablauf.last.ok}
          {ablauf.last.result?.status ?? "fertig"} {ablauf.last.result?.reason ?? ""}
        {:else}
          <span class="bad">{ablauf.last.reason}</span>
        {/if}
      </p>
    {/if}
  </section>

  <section>
    <h2>Anmeldung</h2>
    <div class="knoepfe">
      <button onclick={anmeldestand} disabled={beschaeftigt === "stand"}>Status prüfen</button>
      <button onclick={anmelden} disabled={beschaeftigt === "anmelden" || ablauf?.busy}>
        Anmelden
      </button>
    </div>
    {#if anmeldung}
      <p class="muted klein">
        {#if !anmeldung.known}
          <span class="bad">{anmeldung.reason}</span>
        {:else if anmeldung.signed_in}
          angemeldet
        {:else}
          nicht angemeldet
        {/if}
      </p>
    {/if}
  </section>

  {#if unklar && (unklar.items.length || unklar.open_dispatches.length)}
    <section>
      <h2>Status unklar</h2>
      <p class="muted klein">Hier wird nichts von allein erneut gesendet. Du entscheidest.</p>
      {#each unklar.items as eintrag}
        <div class="karte">
          <div class="zeile">
            <div>
              <strong>{eintrag.title || eintrag.key}</strong>
              <span class="muted klein">{eintrag.reason}</span>
            </div>
            <div class="knoepfe">
              {#each unklar.decisions as entscheidung}
                <button onclick={() => entscheiden(eintrag.key, entscheidung.value)}>
                  {entscheidung.label}
                </button>
              {/each}
            </div>
          </div>
          {#if eintrag.incident}<p class="muted klein">Vorfall: {eintrag.incident}</p>{/if}
        </div>
      {/each}
    </section>
  {/if}

  {#if bestand}
    <section>
      <h2>Bestand</h2>
      <div class="zaehler">
        <button class:aktiv={filter === ""} onclick={() => filterWechseln("")}>
          <strong>{Object.values(bestand.counts).reduce((a, b) => a + b, 0)}</strong>
          <span>alle</span>
        </button>
        {#each Object.entries(bestand.counts) as [status, anzahl]}
          <button class:aktiv={filter === status} onclick={() => filterWechseln(status)}>
            <strong>{anzahl}</strong><span>{status}</span>
          </button>
        {/each}
      </div>
      {#if bestand.items.length === 0}
        <p class="muted klein">Keine Einträge.</p>
      {:else}
        <table>
          <tbody>
            {#each bestand.items.slice(0, 30) as eintrag}
              <tr>
                <td>{eintrag.updated_at?.slice(0, 16).replace("T", " ")}</td>
                <td>{eintrag.status}</td>
                <td class="lang">{eintrag.title || eintrag.key}</td>
                <td class="muted">{eintrag.reason}</td>
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
      {#each vorfaelle.slice(0, 10) as vorfall}
        <div class="karte">
          <div class="zeile">
            <div>
              <strong>{vorfall.operation}</strong>
              <span class="muted klein">{vorfall.reason}</span>
            </div>
            <div class="knoepfe">
              <span class="muted klein">{vorfall.missing} Rolle(n) nicht gefunden</span>
              <button onclick={() => vorfallWeg(vorfall.incident)}>vergessen</button>
            </div>
          </div>
          <p class="muted klein">
            {vorfall.at?.slice(0, 19).replace("T", " ")} · {vorfall.incident}
          </p>
        </div>
      {/each}
    {/if}
  </section>

  <section>
    <h2>Ereignisse</h2>
    <div class="knoepfe">
      <button onclick={() => fuehreAus("neustart", restartService)}>Dienst neu starten</button>
    </div>
    {#if $events.length === 0}
      <p class="muted klein">Noch keine Ereignisse.</p>
    {:else}
      <ul>
        {#each $events.slice(0, 25) as event (event.seq)}
          <li><span class="muted">{event.ts?.slice(11, 23)}</span> <strong>{event.kind}</strong></li>
        {/each}
      </ul>
    {/if}
  </section>
</div>

<style>
  .seite { display: flex; flex-direction: column; gap: 24px; }
  h2 {
    font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--muted); margin: 0 0 8px; padding-bottom: 6px; border-bottom: 1px solid var(--line);
  }
  .knoepfe { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  .eingabe { display: flex; gap: 8px; }
  .eingabe input:first-child { flex: 1; }
  .zaehler { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 8px; }
  .zaehler button {
    display: flex; flex-direction: column; gap: 2px; padding: 8px 10px; text-align: left;
    background: var(--panel); border: 1px solid var(--line); border-radius: 6px;
  }
  .zaehler button.aktiv { border-color: var(--ok); }
  .zaehler strong { font-size: 18px; }
  .zaehler span { font-size: 11px; color: var(--muted); }
  .karte {
    background: var(--panel); border: 1px solid var(--line); border-radius: 6px;
    padding: 8px 10px; margin-bottom: 6px;
  }
  .zeile { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .muted { color: var(--muted); }
  .klein { font-size: 12px; margin: 4px 0 0; }
  .bad, .fehler { color: var(--bad); font-size: 13px; }
  .warnung { color: var(--warn); font-size: 12px; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  td { padding: 3px 8px 3px 0; border-bottom: 1px solid var(--line); vertical-align: top; }
  td.lang { max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  ul { list-style: none; padding: 0; font-size: 13px; margin: 0; }
  li { padding: 4px 0; border-bottom: 1px solid var(--line); }
</style>
