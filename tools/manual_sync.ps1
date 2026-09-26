<#
.SYNOPSIS
  Startet das manuelle Daten-Update für SBR Büchenbach.
.DESCRIPTION
  Führt tools/manual_sync.py mit den übergebenen Argumenten aus.
  Beispiele:
    .\tools\manual_sync.ps1            # Vollständiger lokaler Sync
    .\tools\manual_sync.ps1 -ratsinfo  # Nur Beiratsdokumente
    .\tools\manual_sync.ps1 -rebuildDb # Nur graph.db neu bauen
    .\tools\manual_sync.ps1 -github    # GitHub Actions Workflow starten
#>
[CmdletBinding()]
param(
    [switch]$all,
    [switch]$ratsinfo,
    [switch]$geo,
    [switch]$gremien,
    [switch]$rebuildDb,
    [switch]$noText,
    [switch]$github
)

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$argsList = @()
if ($all) { $argsList += "--all" }
if ($ratsinfo) { $argsList += "--ratsinfo" }
if ($geo) { $argsList += "--geo" }
if ($gremien) { $argsList += "--gremien" }
if ($rebuildDb) { $argsList += "--rebuild-db" }
if ($noText) { $argsList += "--no-text" }
if ($github) { $argsList += "--trigger-github" }

python "$PSScriptRoot\manual_sync.py" @argsList
