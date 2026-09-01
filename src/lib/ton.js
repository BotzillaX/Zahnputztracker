import klang from "../assets/hinweis.wav";

/**
 * Der Signalton bei einem neu gefundenen Eintrag (Spezifikation 12.5).
 *
 * Ob überhaupt geklungen wird, entscheidet der Dienst anhand der
 * Einstellung und hängt es an die Meldung. Hier wird nur abgespielt.
 */
let klingel = null;

export function signalton(ereignis) {
  if (ereignis?.kind !== "notification" || !ereignis.sound) return;
  try {
    if (!klingel) klingel = new Audio(klang);
    klingel.currentTime = 0;
    // Ein stummer oder gesperrter Rechner ist kein Grund, irgendetwas
    // anzuhalten: der Fehler wird geschluckt, die Meldung steht ohnehin
    // in der Oberfläche und im Tray.
    klingel.play()?.catch(() => {});
  } catch {
    /* kein Ton, kein Problem */
  }
}
