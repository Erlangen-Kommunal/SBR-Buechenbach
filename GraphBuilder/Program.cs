using System.Collections.Concurrent;
using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using GraphBuilder;

// GraphBuilder — liest SBR/index.json (vom Sync-Skript uvp_agent.py erzeugt)
// samt heruntergeladener PDFs sowie die kuratierten Register (recht/, statistik/)
// und baut daraus eine DuckDB-Datenbank (documents + plans/plan_files, FTS/BM25)
// für das statische Portal-Frontend des Stadtteilbeirats Büchenbach.
//
// Aufruf:  GraphBuilder [repoRoot] [--db graph.db] [--no-text]

Console.OutputEncoding = Encoding.UTF8;

var repoRoot = "";
var dbPath = "graph.db";
var extractText = true;

for (var i = 0; i < args.Length; i++)
{
    switch (args[i])
    {
        case "--db": dbPath = args[++i]; break;
        case "--no-text": extractText = false; break;
        default: repoRoot = args[i]; break;
    }
}

// Repo-Wurzel = Verzeichnis mit SBR/index.json (notfalls von cwd aus nach oben suchen)
if (repoRoot.Length == 0)
{
    var dir = Directory.GetCurrentDirectory();
    while (dir is not null && !File.Exists(Path.Combine(dir, "SBR", "index.json")))
        dir = Path.GetDirectoryName(dir);
    repoRoot = dir ?? throw new FileNotFoundException(
        "SBR/index.json nicht gefunden — Repo-Wurzel als Argument angeben.");
}

var indexFile = Path.Combine(repoRoot, "SBR", "index.json");
var records = JsonSerializer.Deserialize<List<SbrDocRecord>>(File.ReadAllText(indexFile))
              ?? throw new InvalidDataException($"Konnte {indexFile} nicht parsen.");
// Das Ratsinformationssystem listet dieselbe Datei gelegentlich zweimal unter
// verschiedenen Namen — einmal sprechend, einmal mit interner RIS-Kennung (so bei
// der Niederschrift zur Sitzung 2020-10-20, beide Dateien byte-identisch). Beide
// Einträge tragen eine eigene doc_id, die Prüfung in Phase 1 greift also nicht.
// Ohne diesen Schritt steht das Dokument doppelt im Portal, und die Zusammenfassung
// hängt nur an einem der beiden Namen. Der Index wird bei jedem Sync neu erzeugt,
// deshalb muss die Entdopplung hier sitzen und nicht in der Datei.
bool HasEnrichment(SbrDocRecord r) =>
    File.Exists(Path.Combine(repoRoot, "enrichment", "docs", "SBR", r.Filename + ".md"));

string ContentKey(SbrDocRecord r)
{
    var abs = Path.Combine(repoRoot, "SBR", r.Filename);
    // Ohne lokale Datei lässt sich der Inhalt nicht vergleichen — solche Einträge
    // bleiben über ihre doc_id für sich stehen.
    return File.Exists(abs)
        ? "sha:" + Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(abs)))
        : "id:" + r.DocId;
}

var vorEntdopplung = records.Count;
records = [.. records
    .GroupBy(ContentKey)
    .Select(g => g
        .OrderByDescending(HasEnrichment)      // Anreicherung darf nicht verloren gehen
        .ThenBy(r => r.Filename.Length)        // sonst der sprechendere (kürzere) Name
        .ThenBy(r => r.DocId, StringComparer.Ordinal)
        .First())
    .OrderByDescending(r => r.Date).ThenBy(r => r.Category)];

if (vorEntdopplung != records.Count)
    Console.WriteLine($"Entdopplung: {vorEntdopplung - records.Count} inhaltsgleiche Dokumente übersprungen.");

Console.WriteLine($"GraphBuilder — {records.Count} Dokumente aus {indexFile}");
var sw = Stopwatch.StartNew();

// ── Phase 1: Dokumentzeilen + Volltext-Jobs aus dem Index ────────────────────

var docRows = new List<(DocumentRow Row, string? AbsPath)>();
var seen = new HashSet<string>();

foreach (var r in records)
{
    if (!seen.Add(r.DocId))
        continue;  // doc_id ist eindeutig; Duplikate im Index überspringen
    var relPath = $"SBR/{r.Filename}";
    var absPath = Path.Combine(repoRoot, "SBR", r.Filename);
    var url = $"https://ratsinfo.erlangen.de/{r.Href}";
    docRows.Add((
        new DocumentRow(r.DocId, r.Date, r.Category, r.Title, relPath, url, 0, null),
        File.Exists(absPath) ? absPath : null));
}

Console.WriteLine($"Struktur: {docRows.Count} Dokumente, " +
    $"{docRows.Count(d => d.AbsPath is not null)} lokal vorhanden.");

// ── Phase 2: PDF-Volltexte parallel extrahieren ──────────────────────────────

var texts = new ConcurrentDictionary<string, (string Text, int Pages)>();
if (extractText)
{
    var paths = docRows.Where(d => d.AbsPath is not null).Select(d => d.AbsPath!).Distinct().ToList();
    Parallel.ForEach(
        paths,
        new ParallelOptions { MaxDegreeOfParallelism = Environment.ProcessorCount },
        path => texts[path] = PdfText.Extract(path));
    Console.WriteLine($"Volltext: {paths.Count} PDFs gelesen, " +
        $"{texts.Values.Count(t => t.Text.Length > 0)} mit Text ({sw.Elapsed:mm\\:ss}).");
}

// ── Phase 3: Anreicherung (enrichment/docs/<pfad>.md) einlesen ────────────────

// Frontmatter mit Themen (JSON-Array) + Body-Zusammenfassung; '|' als internem
// Themen-Trenner, da Themennamen Kommas enthalten können.
(string? Summary, string? Themen) ReadEnrichment(string relPath)
{
    var mdPath = Path.Combine(repoRoot, "enrichment", "docs", relPath + ".md");
    if (!File.Exists(mdPath))
        return (null, null);
    var lines = File.ReadAllLines(mdPath);
    if (lines.Length < 3 || lines[0].Trim() != "---")
        return (null, null);
    var end = Array.FindIndex(lines, 1, l => l.Trim() == "---");
    if (end < 0)
        return (null, null);

    string? themen = null;
    foreach (var line in lines[1..end])
    {
        if (line.StartsWith("themen:", StringComparison.Ordinal))
        {
            try
            {
                var list = JsonSerializer.Deserialize<List<string>>(line["themen:".Length..].Trim());
                themen = list is { Count: > 0 } ? string.Join("|", list) : null;
            }
            catch (JsonException) { /* fehlerhafte Frontmatter — Themen auslassen */ }
        }
    }
    var body = string.Join("\n", lines[(end + 1)..]).Trim();
    return (body.Length > 0 ? body : null, themen);
}

var finalDocs = new List<DocumentRow>();
var enrichedCount = 0;
foreach (var (row, absPath) in docRows)
{
    var (text, pages) = absPath is not null && texts.TryGetValue(absPath, out var t) ? t : ("", 0);
    var (summary, themen) = ReadEnrichment(row.Path);
    if (summary is not null)
        enrichedCount++;
    finalDocs.Add(row with
    {
        Pages = pages,
        Text = text.Length > 0 ? text : null,
        Summary = summary,
        Themen = themen,
    });
}

// ── Phase 4: Kuratierte Register (Rechtsvorschriften, Statistik) ──────────────
// Beide Ordner teilen dasselbe registry.json-Format (PlanRecord) und werden
// identisch verarbeitet — nur die Registry-Art (kind) unterscheidet sie.

var planRows = new List<PlanRow>();
var planFileRows = new List<PlanFileRow>();

void LoadRegistry(string folderName, string kind)
{
    var registryFile = Path.Combine(repoRoot, folderName, "registry.json");
    if (!File.Exists(registryFile))
    {
        Console.WriteLine($"Hinweis: {registryFile} nicht gefunden — {folderName} übersprungen.");
        return;
    }

    var items = JsonSerializer.Deserialize<List<PlanRecord>>(File.ReadAllText(registryFile)) ?? [];
    foreach (var item in items)
    {
        var planId = $"{kind}:{item.Id}";  // eindeutig über alle Register hinweg
        planRows.Add(new PlanRow(planId, kind, item.Title, item.Beschreibung,
            item.Erstellt, item.QuelleUrl, string.Join("|", item.Themen)));

        foreach (var file in item.Dateien)
        {
            var absPath = file.Pfad is { Length: > 0 } p ? Path.Combine(repoRoot, p) : null;
            var (text, pages) = extractText && absPath is not null && File.Exists(absPath)
                ? PdfText.Extract(absPath) : ("", 0);
            planFileRows.Add(new PlanFileRow(
                planId, file.Titel,
                absPath is not null && File.Exists(absPath) ? file.Pfad : null,
                file.QuelleUrl, pages, text.Length > 0 ? text : null));
        }
    }
    Console.WriteLine($"{folderName}: {items.Count} Einträge aus {registryFile}, " +
        $"{items.Sum(i => i.Dateien.Count)} Dateien.");
}

LoadRegistry("recht", "recht");
LoadRegistry("statistik", "statistik");

// ── Phase 5: DuckDB schreiben + FTS-Index ────────────────────────────────────

using (var db = new GraphDb(dbPath))
{
    db.CreateSchema();
    db.InsertDocuments(finalDocs);
    db.InsertPlans(planRows);
    db.InsertPlanFiles(planFileRows);
    if (extractText)
        db.CreateFtsIndex();

    Console.WriteLine();
    Console.WriteLine($"graph.db geschrieben: {Path.GetFullPath(dbPath)}");
    Console.WriteLine($"  Dokumente: {db.Count("documents")} " +
        $"(davon {db.Count("documents WHERE text IS NOT NULL")} mit Volltext, " +
        $"{enrichedCount} mit Zusammenfassung)");
    Console.WriteLine($"  Sitzungen: {db.Count("(SELECT DISTINCT date FROM documents)")}");
    Console.WriteLine($"  Recht:     {db.Count("plans WHERE kind = 'recht'")} " +
        $"({db.Count("plan_files pf JOIN plans p ON p.id = pf.plan_id WHERE p.kind = 'recht'")} Dateien)");
    Console.WriteLine($"  Statistik: {db.Count("plans WHERE kind = 'statistik'")} " +
        $"({db.Count("plan_files pf JOIN plans p ON p.id = pf.plan_id WHERE p.kind = 'statistik'")} Dateien)");
}

Console.WriteLine($"Fertig in {sw.Elapsed:mm\\:ss}. " +
    $"DB-Größe: {new FileInfo(dbPath).Length / (1024.0 * 1024.0):F1} MB");
