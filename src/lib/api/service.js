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
