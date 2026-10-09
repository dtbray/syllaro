# Podcast subscription imports

`import-opml PATH` imports subscriptions into the configured data directory while
holding the same exclusive lock as the queue worker. It never makes network requests,
downloads episodes or enqueues work. The existing ingestion timer does not poll these
subscriptions. `feeds` lists IDs, titles, enabled preferences and folder memberships;
it deliberately omits full URLs.

The registry is `feeds/subscriptions.json`, separate from queue job files. Its directory
has mode 0700 and the atomic, durable registry has mode 0600. Feed URLs may include
subscription-specific tokens or HTTP user information; they remain in local private
storage. Do not commit the registry or your original OPML export, and protect backups.
The workstation receives no subscription registry or feed credentials.

The importer accepts UTF-8 OPML with one body and nested outlines. It preserves folder
membership and deduplicates exact feed URLs using stable SHA-256 IDs. Reimporting
merges categories while preserving the existing title and enabled preference. That
preference is stored metadata, not a background-fetch schedule.

Malformed documents, unsupported document types/entities, oversized input and corrupt
persisted registries are rejected before replacing subscriptions. The import report
counts added/existing/skipped entries and always reports zero episodes queued. Valid
entries can be retained when other entries are invalid; skipped entries produce error
details without the supplied URL and a nonzero CLI exit. Symlinked registry paths are
rejected to keep persisted artifacts within the configured data directory.

Future episode intake must add an explicit media job type with feed/item identity,
GUID/enclosure provenance, deduplication, bounded downloads, redirect/authentication
handling and explicit selection limits. Authenticated subscriptions are stored now,
but no credentials are sent or tested. Cached audio can then use the separately
validated workstation speech handoff. Summarization/action-item generation remains a
separate stage with no automatic cloud inference fallback.
