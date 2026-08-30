import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { pushEvent, serviceStatus } from "../stores/service.js";

let socket = null;
let lastSeq = 0;
let reconnectTimer = null;

async function endpoint() {
  return await invoke("service_endpoint");
}

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

export async function health() {
  const { port, token } = await endpoint();
  const response = await fetch(`http://127.0.0.1:${port}/health`, {
    headers: { "X-Auth-Token": token }
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return await response.json();
}

export async function sendPing() {
  const { port, token } = await endpoint();
  const response = await fetch(`http://127.0.0.1:${port}/ping`, {
    method: "POST",
    headers: { "X-Auth-Token": token }
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return await response.json();
}

export async function restartService() {
  return await invoke("service_restart");
}
