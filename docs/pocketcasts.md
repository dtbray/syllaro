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
complete synchronization. It reads recent listening history but does not modify playback or import bookmarks.

## Completed episodes are excluded by default

Each subscription sync also reads `/user/history` and merges positive completion
evidence into private, durable `feeds/pocketcasts-listening.json`. The default
screening list excludes episodes with `playingStatus == 3` (completed), including
shows on your explicit priority list. Partially played episodes remain eligible;
a percentage threshold is not applied. Archived/deleted flags do not mean heard.

Matching uses the exact feed identity and media URL, with an exact feed, title,
and publication timestamp fallback for changed media URLs. Titles are only
whitespace-normalized and HTML-unescaped; there is no fuzzy title-only matching.
The ledger stores hashed matching signatures rather than titles or media URLs.
Missing matches mean unknown listening status, not confirmed unplayed. Refreshing
RSS metadata does not remove completion evidence. A later history response that
omits old episodes or marks an episode unplayed does not erase a known completion.

The current web history endpoint returned only 100 recent entries in live tests;
page/offset parameters did not retrieve older entries. Ordinary recent-history syncs report `recent_history_only` until a yearly
backfill has been completed. Older listens not already in the ledger may still
appear. Subsequent syncs accumulate new completions. Failed history reads retain the ledger and return a nonzero sync
exit, even if subscription merging succeeded. There is no background sync unless
you arrange one explicitly.

To inspect excluded episodes:

```bash
syllaro --config ~/.config/syllaro/config.json screening --include-listened
syllaro --config ~/.config/syllaro/config.json screening --decision skip
```

An explicit episode-level `screening-override EPISODE_ID process` or `review`
resurfaces that episode; a feed-level priority does not bypass the exclusion.
`auto` restores default exclusion. Automatic rules for essential information or
potential action items are deferred until defined; no inferred exception is applied.

The persistent-history approach was informed by
[DanEEStar/listening-history-deno](https://github.com/DanEEStar/listening-history-deno/blob/main/server/services/pocketCasts.ts).
Its 70% playback threshold is not used. Pocket Casts' own
[playing-status definitions](https://github.com/Automattic/pocket-casts-android/blob/main/modules/services/model/src/main/java/au/com/shiftyjelly/pocketcasts/models/type/EpisodePlayingStatus.kt)
identify completed episodes as status 3.

## Year-based history backfill

The iOS app uses a separate `/history/year` endpoint. It first reads a year count,
then requests that year's interactions. Syllaro follows this read-only route when
`--history-since-year` is supplied:

```bash
op run --env-file ~/.config/syllaro/pocketcasts.env -- \
  syllaro --config ~/.config/syllaro/config.json sync-pocketcasts --login \
  --history-since-year 2025
```

The selected range extends through the current UTC year. Each response must match
its reported year count. History entries alone do not establish completion:
Syllaro separately reads `/user/podcast/episodes` for each currently subscribed
show and only accepts status 3 as completed. It ignores history delete/clear
changes for new evidence and retains previously verified completions. No history
or episode state is written to Pocket Casts. Two concurrent requests bound the
per-show playback lookup; metadata responses retain the size and timeout limits.

Coverage and the checked year range are persisted in the private ledger. Failed
show reads or missing playback states are reported as a partial backfill and a
nonzero sync exit. Previously verified completions survive. Ordinary subsequent
recent-history syncs preserve the backfilled ledger. A selected year range does
not prove that every earlier year is empty, or that entries from unsubscribed
shows were imported.

Live validation on 2026-10-09 returned 1,147 interactions for 2025 and 441 for
2026. Of the 1,551 distinct interactions mapped to subscribed shows, 1,385 had
verified completed state and 166 were partial/unplayed, with no failed show reads
or missing playback states. Combined with recent-history evidence, 28 indexed RSS
episodes matched completion evidence, including three previously recommended
for processing. The production queue and downloaded media were untouched.

Source: [iOS year-history implementation](https://github.com/Automattic/pocket-casts-ios/blob/trunk/Modules/Sources/PocketCastsServer/Public/Sync/SyncYearListeningHistoryTask.swift).
