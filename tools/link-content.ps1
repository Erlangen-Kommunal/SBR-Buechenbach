# Verbindet web/content mit dem kanonischen content/ im Repo-Wurzelverzeichnis.
#
# Warum das nötig ist: Das Frontend lädt `content/<name>.json` relativ zur Seite,
# im Deploy liegt das Verzeichnis durch `cp -r content _site/content` neben der
# index.html. Beim lokalen Entwickeln wird `web/` direkt ausgeliefert, dort muss
# `content/` also ebenfalls erreichbar sein.
#
# Früher lag dort eine echte Kopie — die ist auseinandergelaufen: `web/content/`
# ist gitignored, also blieben Änderungen daran unbemerkt lokal, während die
# ausgelieferte Datei monatelang alt war. Eine Junction macht das unmöglich,
# weil beide Pfade auf dieselben Dateien zeigen.
#
# Aufruf:  pwsh -File tools/link-content.ps1

$ErrorActionPreference = 'Stop'

$repo = Split-Path -Parent $PSScriptRoot
$src  = Join-Path $repo 'content'
$dst  = Join-Path $repo 'web\content'

if (-not (Test-Path $src)) { throw "Kanonisches Verzeichnis fehlt: $src" }

if (Test-Path $dst) {
  $item = Get-Item $dst -Force
  if ($item.LinkType -eq 'Junction') {
    Write-Host "Junction besteht bereits: $dst -> $($item.Target -join '')"
    exit 0
  }
  # Echte Kopie vorgefunden: nur entfernen, wenn sie nichts Eigenes enthält.
  $abweichend = @()
  foreach ($f in Get-ChildItem $dst -File) {
    $gegen = Join-Path $src $f.Name
    if (-not (Test-Path $gegen)) { $abweichend += "$($f.Name) (nur in web/content)" }
    elseif ((Get-FileHash $f.FullName).Hash -ne (Get-FileHash $gegen).Hash) { $abweichend += "$($f.Name) (Inhalt weicht ab)" }
  }
  if ($abweichend) {
    Write-Host "ABBRUCH — web/content enthält Stände, die in content/ fehlen:" -ForegroundColor Red
    $abweichend | ForEach-Object { Write-Host "  $_" }
    Write-Host "Bitte zuerst nach content/ übernehmen, dann erneut aufrufen."
    exit 1
  }
  Remove-Item $dst -Recurse -Force
}

New-Item -ItemType Junction -Path $dst -Target $src | Out-Null
Write-Host "Junction angelegt: $dst -> $src"
