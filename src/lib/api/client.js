import { invoke } from "@tauri-apps/api/core";

/** Port und Token des laufenden Dienstes, vom Kern verwaltet. */
export async function endpoint() {
  return await invoke("service_endpoint");
}

/** Aufruf an den Dienst. Wirft mit der Klartextmeldung des Dienstes. */
export async function request(pfad, { method = "GET", body } = {}) {
  const { port, token } = await endpoint();
  const antwort = await fetch(`http://127.0.0.1:${port}${pfad}`, {
    method,
    headers: {
      "X-Auth-Token": token,
      ...(body === undefined ? {} : { "Content-Type": "application/json" })
    },
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  const text = await antwort.text();
  const daten = text ? JSON.parse(text) : null;
  if (!antwort.ok) {
    const meldung = daten?.detail ?? `HTTP ${antwort.status}`;
    throw new Error(typeof meldung === "string" ? meldung : JSON.stringify(meldung));
  }
  return daten;
}
