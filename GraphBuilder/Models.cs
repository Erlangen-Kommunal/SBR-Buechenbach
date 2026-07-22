using System.Text.Json.Serialization;

namespace GraphBuilder;

/// <summary>
/// Ein Dokument aus SBR/index.json (vom Sync-Skript uvp_agent.py erzeugt).
/// Der Stadtteilbeirat hat eine flache Struktur: je Sitzungstermin (date)
/// eine Einladung, eine Niederschrift und ggf. Anhänge — keine TOP/Vorlage-Ebene.
/// </summary>
public sealed class SbrDocRecord
{
    [JsonPropertyName("doc_id")] public string DocId { get; set; } = "";
    [JsonPropertyName("date")] public string Date { get; set; } = "";
    [JsonPropertyName("category")] public string Category { get; set; } = "";  // Einladung | Niederschrift | Anhang
    [JsonPropertyName("title")] public string Title { get; set; } = "";
    [JsonPropertyName("filename")] public string Filename { get; set; } = "";
    [JsonPropertyName("href")] public string Href { get; set; } = "";
}

/// <summary>
/// Ein Schreiben des Stadtteilbeirats aus dem kuratierten Register SBR/antraege.json:
/// Anträge, Stellungnahmen und Briefe an Oberbürgermeister, Fraktionen und Stadtrat.
/// Diese Dokumente stehen nicht im Ratsinformationssystem und kommen deshalb nicht
/// über den Sync, sondern von Hand — daher ein eigenes Register neben index.json,
/// die der Sync bei jedem Lauf neu schreibt.
/// </summary>
public sealed class AntragRecord
{
    [JsonPropertyName("id")] public string Id { get; set; } = "";
    [JsonPropertyName("date")] public string Date { get; set; } = "";  // Datum des Schreibens
    [JsonPropertyName("title")] public string Title { get; set; } = "";
    [JsonPropertyName("datei")] public string Datei { get; set; } = "";  // Pfad unterhalb von SBR/
    [JsonPropertyName("themen")] public List<string> Themen { get; set; } = [];
    [JsonPropertyName("zusammenfassung")] public string? Zusammenfassung { get; set; }
    [JsonPropertyName("anlagen")] public List<AntragAnlage> Anlagen { get; set; } = [];
}

public sealed class AntragAnlage
{
    [JsonPropertyName("titel")] public string Titel { get; set; } = "";
    [JsonPropertyName("datei")] public string Datei { get; set; } = "";
}

/// <summary>Ein kuratierter externer Eintrag aus recht/ bzw. statistik/registry.json.</summary>
public sealed class PlanRecord
{
    [JsonPropertyName("id")] public string Id { get; set; } = "";
    [JsonPropertyName("title")] public string Title { get; set; } = "";
    [JsonPropertyName("beschreibung")] public string Beschreibung { get; set; } = "";
    [JsonPropertyName("erstellt")] public string? Erstellt { get; set; }
    [JsonPropertyName("themen")] public List<string> Themen { get; set; } = [];
    [JsonPropertyName("quelle_url")] public string? QuelleUrl { get; set; }
    [JsonPropertyName("dateien")] public List<PlanFile> Dateien { get; set; } = [];
}

public sealed class PlanFile
{
    [JsonPropertyName("titel")] public string Titel { get; set; } = "";
    [JsonPropertyName("pfad")] public string? Pfad { get; set; }
    [JsonPropertyName("quelle_url")] public string? QuelleUrl { get; set; }
}
