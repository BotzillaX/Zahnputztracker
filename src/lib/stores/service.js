import { writable } from "svelte/store";

/** Verbindungszustand des Dienstes, wie ihn der Kern meldet. */
export const serviceStatus = writable({ state: "unbekannt", detail: "" });

/** Stand des Update-Knopfes, wie ihn der Kern meldet (Spez. 13.4). */
export const updateStand = writable({ state: "aktuell", current: "", version: "", detail: "" });

/** Die letzten Ereignisse aus dem Livestrom, neuestes zuerst. */
export const events = writable([]);

const MAX_EVENTS = 200;

export function pushEvent(event) {
  events.update((list) => [event, ...list].slice(0, MAX_EVENTS));
}
