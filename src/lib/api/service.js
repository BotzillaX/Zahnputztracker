import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { pushEvent, serviceStatus } from "../stores/service.js";
import { signalton } from "../ton.js";
import { endpoint, request } from "./client.js";

let socket = null;
let lastSeq = 0;
let reconnectTimer = null;

/** Baut den Ereignisstrom auf und hält ihn offen. */
async function connectStream() {
  const { port, token } = await endpoint();
  if (socket) {
    socket.close();
    socket = null;
  }
  const url = `ws://127.0.0.1:${port}/events?token=${encodeURIComponent(token)}&after=${lastSeq}`;
  socket = new WebSocket(url);
  socket.onmessage = (message) => {
    const event = JSON.parse(message.data);
    if (event.kind === "heartbeat") return;
    if (typeof event.seq === "number") lastSeq = event.seq;
    pushEvent(event);
    signalton(event);
  };
  socket.onclose = () => {
    socket = null;
    scheduleReconnect();
  };
  socket.onerror = () => socket && socket.close();
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connectStream().catch(() => scheduleReconnect());
  }, 1500);
}

/** Einmalige Einrichtung: Statusmeldungen des Kerns abonnieren, Strom öffnen. */
export async function initService() {
  await listen("service-status", (message) => {
    serviceStatus.set(message.payload);
    if (message.payload.state === "verbunden") {
      connectStream().catch(() => scheduleReconnect());
    }
  });
  const current = await invoke("service_status");
  serviceStatus.set(current);
  if (current.state === "verbunden") await connectStream();
}

export const health = () => request("/health");
export const sendPing = () => request("/ping", { method: "POST" });
export const restartService = () => invoke("service_restart");

export const ladeEinstellungen = () => request("/config");
export const speichereEinstellungen = (daten) =>
  request("/config", { method: "PUT", body: daten });

export const ladeGeheimnisse = () => request("/secrets");
export const setzeGeheimnis = (name, wert) =>
  request(`/secrets/${name}`, { method: "PUT", body: { value: wert } });
export const loescheGeheimnis = (name) => request(`/secrets/${name}`, { method: "DELETE" });

export const ladeEintraege = (status) =>
  request(`/items${status ? `?status=${encodeURIComponent(status)}` : ""}`);
export const ladeUnklare = () => request("/items/unclear");

export const ladeBrowser = () => request("/browser");
export const starteBrowser = () => request("/browser/start", { method: "POST" });
export const stoppeBrowser = () => request("/browser/stop", { method: "POST" });
export const ladeBrowserProgramm = (ersetzen = false) =>
  request("/browser/install", { method: "POST", body: { replace: ersetzen } });
export const setzePause = (pausiert) =>
  request("/browser/pause", { method: "POST", body: { paused: pausiert } });
export const setzeSichtbar = (rolle, sichtbar) =>
  request(`/browser/${rolle}/visibility`, { method: "POST", body: { visible: sichtbar } });
export const gehZu = (rolle, url) =>
  request(`/browser/${rolle}/navigate`, { method: "POST", body: url ? { url } : {} });
export const zaehleFenster = (pids) => invoke("browser_window_count", { pids });

export const ladeRegistrierung = (bereich) => request(`/registry/${bereich}`);
export const speichereRegistrierung = (bereich, dokument) =>
  request(`/registry/${bereich}`, { method: "PUT", body: dokument });
export const ladeGrundkatalog = (bereich) => request(`/registry/${bereich}/catalogue`);
export const uebernimmGrundkatalog = (bereich) =>
  request(`/registry/${bereich}/catalogue`, { method: "POST" });
export const speichereRolle = (bereich, rolle) =>
  request(`/registry/${bereich}/roles/${rolle.id}`, { method: "PUT", body: rolle });
export const loescheRolle = (bereich, id) =>
  request(`/registry/${bereich}/roles/${id}`, { method: "DELETE" });
export const ladeVersionen = (bereich) => request(`/registry/${bereich}/history`);
export const ladeAblaufplan = (bereich) => request(`/registry/${bereich}/plan`);
export const setzeZurueck = (bereich, version) =>
  request(`/registry/${bereich}/restore`, { method: "POST", body: { version } });
export const exportiereRegistrierung = (bereich) =>
  request(`/registry/${bereich}/export`, { method: "POST" });
export const importiereRegistrierung = (bereich, dokument) =>
  request(`/registry/${bereich}/import`, { method: "POST", body: { document: dokument } });
export const freieKennung = (bereich, wunsch) =>
  request(`/registry/${bereich}/new-id?wanted=${encodeURIComponent(wunsch || "rolle")}`);
export const pruefeRollen = (bereich, rolle) =>
  request(`/registry/${bereich}/check`, { method: "POST", body: rolle ? { role: rolle } : {} });

export const ladePicker = () => request("/picker");
export const startePicker = (bereich) => request(`/picker/${bereich}/start`, { method: "POST" });
export const stoppePicker = (bereich) => request(`/picker/${bereich}/stop`, { method: "POST" });
export const verwirfAuswahl = () => request("/picker/picks", { method: "DELETE" });
export const vergissAuswahl = (nummer) =>
  request(`/picker/picks/${nummer}`, { method: "DELETE" });
export const fuegeAuswahlEin = (text, notiz, bereich) =>
  request("/picker/picks", { method: "POST", body: { text, note: notiz ?? "", scope: bereich } });
export const oeffneKopie = (bereich, ansicht, herkunft) =>
  request(`/picker/${bereich}/snapshot`, {
    method: "POST",
    body: { view: ansicht, from: herkunft ?? bereich }
  });
export const gibNetzFrei = (bereich) => request(`/picker/${bereich}/release`, { method: "POST" });

export const ladeAnsichten = (bereich) =>
  request(`/atlas${bereich ? `?scope=${encodeURIComponent(bereich)}` : ""}`);
export const merkeAnsicht = (bereich) => request(`/atlas/${bereich}/capture`, { method: "POST" });
export const vergissAnsicht = (bereich, ansicht) =>
  request(`/atlas/${bereich}/${ansicht}`, { method: "DELETE" });
export const ladeKarte = (bereich) =>
  request(`/atlas/map${bereich ? `?scope=${encodeURIComponent(bereich)}` : ""}`);

export const ladeZustaende = (bereich) => request(`/states/${bereich}`);
export const speichereZustand = (bereich, zustand) =>
  request(`/states/${bereich}/${zustand.id}`, { method: "PUT", body: zustand });
export const loescheZustand = (bereich, id) =>
  request(`/states/${bereich}/${id}`, { method: "DELETE" });
export const freieZustandsKennung = (bereich, wunsch) =>
  request(`/states/${bereich}/new-id?wanted=${encodeURIComponent(wunsch || "zustand")}`);
export const erkenneZustand = (bereich) =>
  request(`/states/${bereich}/detect`, { method: "POST" });
export const fuehreKetteAus = (bereich) => request(`/states/${bereich}/run`, { method: "POST" });

export const ladeFreigabe = () => request("/approval");
export const beantworteFreigabe = (id, entscheidung, eingabe) =>
  request("/approval/answer", {
    method: "POST",
    body: { id, decision: entscheidung, value: eingabe ?? "" }
  });

export const ladeVariablen = () => request("/variables");
export const oeffneVorgang = (kennung) =>
  request("/variables/open", { method: "POST", body: { key: kennung ?? "" } });

export const ladeVorlagen = (bereich) =>
  request(`/templates${bereich ? `?scope=${encodeURIComponent(bereich)}` : ""}`);
export const schalteVorlagen = (an) =>
  request("/templates/switch", { method: "POST", body: { enabled: an } });
export const stelleVorlagenHer = () => request("/templates/reset", { method: "POST" });
export const loescheVorlage = (id) => request(`/templates/${id}`, { method: "DELETE" });
export const uebernimmVorlage = (id, bereich) =>
  request(`/templates/${id}/apply/${bereich}`, { method: "POST" });

export const ladeAblauf = () => request("/flow");
export const ladeAnmeldestand = () => request("/flow/sign-in");
export const starteAnmeldung = () => request("/flow/sign-in", { method: "POST" });
export const starteVorgang = (adresse, titel) =>
  request("/flow/contact", { method: "POST", body: { url: adresse, title: titel ?? "" } });
export const ladeSuchlauf = () => request("/flow/search");
export const starteSuchlauf = () => request("/flow/search", { method: "POST" });
export const brichVorgangAb = () => request("/flow/stop", { method: "POST" });
export const ladeTexthilfe = () => request("/text/help");

export const entscheideEintrag = (kennung, entscheidung) =>
  request("/items/decision", { method: "POST", body: { key: kennung, decision: entscheidung } });

export const ladeVorfaelle = () => request("/incidents");
export const ladeVorfall = (kennung) => request(`/incidents/${kennung}`);
export const vergissVorfall = (kennung) => request(`/incidents/${kennung}`, { method: "DELETE" });
export const oeffneVorfallImPicker = (kennung, bereich, datei) =>
  request(`/incidents/${kennung}/picker`, {
    method: "POST",
    body: { scope: bereich, name: datei ?? "seite.html" }
  });

export const ladeDiagnose = () => request("/diagnose");
export const ladeLaufzeiten = () => request("/diagnose/stats");
export const ladeProtokoll = (anzahl) => request(`/diagnose/log?count=${anzahl ?? 200}`);
export const ladeSpeicher = () => request("/diagnose/storage");
export const raeumeAuf = () => request("/diagnose/cleanup", { method: "POST" });
export const ladeBerichte = () => request("/diagnose/reports");
export const erzeugeBericht = (tag) =>
  request("/diagnose/report", { method: "POST", body: { day: tag ?? "" } });
export const halteVorgangAn = (name, sekunden, bereich) =>
  request("/diagnose/probe", {
    method: "POST",
    body: { name, seconds: sekunden, scope: bereich }
  });
