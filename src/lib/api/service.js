import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { pushEvent, serviceStatus } from "../stores/service.js";
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
export const verwirfAuswahl = () => request("/picker/clear", { method: "POST" });
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
