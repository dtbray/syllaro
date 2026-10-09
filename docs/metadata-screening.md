# Metadata-first podcast screening

`screen-feeds` reads subscription RSS/Atom documents and ranks episodes using titles
and show notes. It never follows enclosures, episode-page links or external Atom
content. RSS exposes item titles/descriptions and enclosure references; Atom exposes
entry content/summaries and links. See the [RSS specification](https://www.rssboard.org/rss-specification)
and [Atom specification](https://www.rfc-editor.org/rfc/rfc4287).

```sh
# Default: first 20 enabled subscriptions, up to five dated entries from each.
syllaro --config ~/.config/syllaro/config.json screen-feeds
# Explicitly scan the whole imported collection with a custom preference profile:
syllaro --config ~/.config/syllaro/config.json screen-feeds \
  --profile ~/.config/syllaro/feed-screening.json --feed-limit 376 --episodes-per-feed 5
syllaro --config ~/.config/syllaro/config.json screening --decision process --limit 30
syllaro --config ~/.config/syllaro/config.json screening --query "disaster recovery"
syllaro --config ~/.config/syllaro/config.json screening --scope feed --limit 30
syllaro --config ~/.config/syllaro/config.json screening-override EPISODE_ID skip
syllaro --config ~/.config/syllaro/config.json screening-override FEED_ID process --scope feed
# Remove an override without deleting metadata:
syllaro --config ~/.config/syllaro/config.json screening-override EPISODE_ID auto
```

Decisions are **recommendations**, not processing jobs. The default versioned keyword
profile favors actionable systems/software/AI/MSP/DIY material. It records matched
topics, practical cues, score and rationale. It makes no model calls and is not a
trained or calibrated taste selector. Missing/thin show notes and unmatched topics
go to `review`; explicit exclusion terms and duplicate metadata can produce `skip`.
No enclosure advertised also produces `review`. Duplicate detection means identical
indexed title/notes, not an inference about semantic novelty or whether audio was heard.
Confidence is deliberately low; metadata is untrusted evidence, not instructions or
proof of actual action items, owners or deadlines.

Profiles are version-1 JSON with `topics` (topic to term-list mappings),
`priority_topics`, `action_terms`, and `exclude_terms`. Edit a profile and pass it
explicitly with `--profile`; stored metadata is rescored without needing audio.
Manual feed and episode decisions persist across metadata refreshes. Episode
preferences win over feed preferences. A feed preference to process still leaves
thin episode notes for review; an explicit episode override can override that choice.

The private catalog is `feeds/screening/catalog.json`, in a 0700 directory with
0600 JSON files. Full feed URLs, GUID/enclosure references and authentication material
are omitted from normal review output; catalog data and any exported review report
must stay outside Git. Public HTTP(S) destinations are checked, environment proxies
are disabled, and redirects cannot downgrade HTTPS or forward Authorization across
origins. Basic credentials from an imported URL are used only over HTTPS to its
origin. No cookies or inference profiles are sent to feeds.

Requests use four concurrent workers, a configurable socket timeout (default 15 s,
maximum 60 s) and a 5 MiB metadata limit. DNS resolution follows the system resolver
and has its own timeout behavior. Audio/video responses are refused before body
reads. Oversized XML is sampled from complete leading entries in its bounded prefix
(up to five); output marks publisher order as **not guaranteed newest**. No external
DTD/entity is processed. HTML notes are reduced to text, with script/style content
discarded. Full-feed entries are sorted by available publication timestamps; missing
dates retain publisher ordering.

Fresh metadata is reused for one hour; `--refresh` makes a conditional HTTP request
using ETag/Last-Modified when available. Changed metadata updates stable feed/GUID
identities without losing overrides. Failed refreshes preserve old evidence and mark
it stale. Errors and unselected feeds are counted; any fetch failure makes the command
exit nonzero after persisting successful results. Failed feeds remain subscribed.

Screening uses a separate exclusive lock, so it never claims or blocks audio workers'
queue lock. Periodic durable snapshots preserve collected metadata during longer
scans. No RSS download/transcription jobs, schedule or cloud inference fallback are
enabled by these commands. Episode audio intake remains a separate explicit step.
