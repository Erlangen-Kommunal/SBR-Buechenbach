using DuckDB.NET.Data;

namespace GraphBuilder;

/// <summary>Zeile für die documents-Tabelle (Sitzungsdokumente, Volltext-Basis für FTS).</summary>
public sealed record DocumentRow(
    string Id, string Date, string Category, string Title,
    string Path, string Url, int Pages, string? Text,
    string? Summary = null, string? Themen = null);

/// <summary>Zeile für plans (kuratierte Register: Rechtsvorschriften, Statistik).</summary>
public sealed record PlanRow(
    string Id, string Kind, string Title, string Beschreibung,
    string? Erstellt, string? QuelleUrl, string Themen);

public sealed record PlanFileRow(
    string PlanId, string Titel, string? Path, string? QuelleUrl, int Pages, string? Text);

/// <summary>Kapselt Schema, Bulk-Inserts (Appender) und FTS-Aufbau der graph.db.</summary>
public sealed class GraphDb : IDisposable
{
    private readonly DuckDBConnection _conn;

    public GraphDb(string dbPath)
    {
        if (File.Exists(dbPath))
            File.Delete(dbPath);
        _conn = new DuckDBConnection($"Data Source={dbPath}");
        _conn.Open();
    }

    public void CreateSchema() => Execute(
        """
        CREATE TABLE documents (
            id        VARCHAR PRIMARY KEY,    -- doc_id aus dem Ratsinformationssystem
            date      DATE,                   -- Sitzungsdatum (Termin des Stadtteilbeirats)
            category  VARCHAR,                -- Einladung | Niederschrift | Anhang
            title     VARCHAR,
            path      VARCHAR,                -- Repo-Pfad (SBR/<datei>.pdf) für jsDelivr-Einbettung
            url       VARCHAR,                -- Original-URL im Ratsinformationssystem
            pages     INTEGER,
            text      VARCHAR,                -- extrahierter Volltext (NULL = Scan/fehlt), '\f' = Seitentrenner
            summary   VARCHAR,                -- Kurzzusammenfassung (enrichment/docs/<pfad>.md)
            themen    VARCHAR                 -- '|'-getrennte Themen aus der Taxonomie
        );

        CREATE TABLE plans (
            id           VARCHAR PRIMARY KEY, -- '{kind}:{registry-id}', z. B. 'recht:ortsbeiraete', 'statistik:sozialstruktur-2026'
            kind         VARCHAR NOT NULL,     -- recht | statistik
            title        VARCHAR NOT NULL,
            beschreibung VARCHAR,
            erstellt     VARCHAR,
            quelle_url   VARCHAR,
            themen       VARCHAR
        );

        CREATE TABLE plan_files (
            plan_id    VARCHAR NOT NULL,       -- verweist auf plans.id
            titel      VARCHAR,
            path       VARCHAR,                -- Repo-Pfad, NULL wenn nur extern verlinkt (große PDFs)
            quelle_url VARCHAR,
            pages      INTEGER,
            text       VARCHAR                 -- extrahierter Volltext, für FTS mitindiziert
        );
        """);

    public void InsertDocuments(IEnumerable<DocumentRow> docs)
    {
        using var appender = _conn.CreateAppender("documents");
        foreach (var d in docs)
        {
            var row = appender.CreateRow();
            row.AppendValue(d.Id)
               .AppendValue(string.IsNullOrEmpty(d.Date) ? (DateTime?)null : DateTime.Parse(d.Date))
               .AppendValue(d.Category).AppendValue(d.Title).AppendValue(d.Path)
               .AppendValue(d.Url).AppendValue(d.Pages).AppendValue(d.Text)
               .AppendValue(d.Summary).AppendValue(d.Themen).EndRow();
        }
    }

    public void InsertPlans(IEnumerable<PlanRow> plans)
    {
        using var appender = _conn.CreateAppender("plans");
        foreach (var p in plans)
        {
            var row = appender.CreateRow();
            row.AppendValue(p.Id).AppendValue(p.Kind).AppendValue(p.Title).AppendValue(p.Beschreibung)
               .AppendValue(p.Erstellt).AppendValue(p.QuelleUrl).AppendValue(p.Themen).EndRow();
        }
    }

    public void InsertPlanFiles(IEnumerable<PlanFileRow> files)
    {
        using var appender = _conn.CreateAppender("plan_files");
        foreach (var f in files)
        {
            var row = appender.CreateRow();
            row.AppendValue(f.PlanId).AppendValue(f.Titel).AppendValue(f.Path)
               .AppendValue(f.QuelleUrl).AppendValue(f.Pages).AppendValue(f.Text).EndRow();
        }
    }

    /// <summary>BM25-Volltextindex (deutscher Stemmer) auf Titel + Zusammenfassung + Volltext.</summary>
    public void CreateFtsIndex() => Execute(
        """
        INSTALL fts;
        LOAD fts;
        PRAGMA create_fts_index('documents', 'id', 'title', 'summary', 'text', stemmer='german', stopwords='none');
        PRAGMA create_fts_index('plan_files', 'rowid', 'titel', 'text', stemmer='german', stopwords='none');
        """);

    public long Count(string table)
    {
        using var cmd = _conn.CreateCommand();
        cmd.CommandText = $"SELECT count(*) FROM {table}";
        return (long)cmd.ExecuteScalar()!;
    }

    private void Execute(string sql)
    {
        using var cmd = _conn.CreateCommand();
        cmd.CommandText = sql;
        cmd.ExecuteNonQuery();
    }

    public void Dispose() => _conn.Dispose();
}
