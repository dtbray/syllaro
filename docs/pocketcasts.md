# Pocket Casts subscription sync

`sync-pocketcasts` is an experimental, read-only account adapter inspired by the
StoryGraph client's remembered-session transport. It merges account subscriptions
into the same private registry used by OPML and RSS/Atom screening. Existing feed
IDs, enabled settings, categories and screening overrides remain intact. It never
unsubscribes feeds missing from the account, changes playback state, downloads
media, or queues processing. Exact feed URLs identify duplicates; URL changes
are separate feeds rather than guessed identity matches.

## 1Password credentials

Use your installed 1Password CLI to inject secrets into the command's environment.
Create a private environment-reference file outside Git, such as
`~/.config/syllaro/pocketcasts.env`, containing references (not actual secrets):

```dotenv
POCKETCASTS_EMAIL=op://YOUR_VAULT/YOUR_ITEM/username
POCKETCASTS_PASSWORD=op://YOUR_VAULT/YOUR_ITEM/password
```

```bash
op run --env-file ~/.config/syllaro/pocketcasts.env -- \
  syllaro --config ~/.config/syllaro/config.json sync-pocketcasts --login
```

Choose your actual item references in 1Password. Passwords and the returned token
stay in process memory; neither is saved in Syllaro's configuration, subscription
registry, diagnostics or reports. Login is explicit and is never automatically
retried. Live account validation on 2026-10-09 resolved all 376 subscriptions to existing
RSS feeds with zero skipped entries and zero queued episodes. Mocked tests cover
failure handling separately.

Alternatively inject `POCKETCASTS_TOKEN`, or supply `--token-file` with a private
0600 file. Never supply credentials directly in shell command arguments. An
explicit `--firefox-profile /path/to/profile` can read known Pocket Casts token
cookie/localStorage keys without modifying the browser. This is a limited
adapter, not general browser login discovery: unknown keys, compressed localStorage
values, expired sessions or multiple different tokens require another credential
source. No browser cookies/profiles are exported or persisted.

## Metadata screening

After a successful sync, use the existing screening commands:

```bash
syllaro --config ~/.config/syllaro/config.json screen-feeds --feed-limit 1000
syllaro --config ~/.config/syllaro/config.json screening --scope feed --limit 1000
```

Sync fetches subscription JSON and resolves RSS URLs by UUID through
`refresh.pocketcasts.com/import/export_feed_urls`. The list’s `url` field is a
show website, not its RSS URL, and is never imported as a feed. It never follows episode enclosure URLs. The account
token goes only to the fixed HTTPS account host, not the feed-export or RSS hosts. Redirects and environment HTTP proxies are disabled. Responses are
bounded to 5 MiB and requests time out. Failed entries are counted and produce a
nonzero CLI exit; authentication failures and unrecognized list envelopes leave
the registry unchanged. Successful entries from a partial response are retained.
Removed account subscriptions do not disable existing local feeds.

Pocket Casts [does not offer a public API](https://support.pocketcasts.com/knowledge-base/pocket-casts-api/).
The account list endpoint also appears in its
[Android client](https://github.com/Automattic/pocket-casts-android/blob/main/modules/services/servers/src/main/java/au/com/shiftyjelly/pocketcasts/servers/sync/SyncService.kt),
which now uses protobuf for some requests. This adapter targets the private web
JSON interface; it reports incompatible responses instead of silently claiming
complete synchronization. It does not implement account playback/history or
bookmark import yet.
