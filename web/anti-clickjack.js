// Clickjacking-Schutz: Wenn in fremden iFrames eingebettet, Anzeige unterbinden.
// Synchron im Head geladen, damit die Seite auch dann sichtbar wird, wenn
// externe ES-Modul-Imports (wie DuckDB-Wasm) fehlschlagen oder blockiert sind.
if (window.top !== window.self) {
  try {
    window.top.location = window.self.location;
  } catch {
    document.documentElement.style.display = "none";
  }
} else {
  document.getElementById("antiClickjack")?.remove();
}
