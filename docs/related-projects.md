# Projects to learn from

Checked against project READMEs on 2026-10-02. These are design references, not
a claim that Syllaro must adopt their dependencies or entire architecture.

- [steipete/summarize](https://github.com/steipete/summarize): Point at any URL/YouTube/Podcast or file. Get the gist. CLI and Chrome Extension.
- [m-bain/whisperX](https://github.com/m-bain/whisperX): WhisperX:  Automatic Speech Recognition with Word-level Timestamps (& Diarization)
- [ahmetoner/whisper-asr-webservice](https://github.com/ahmetoner/whisper-asr-webservice): OpenAI Whisper ASR Webservice API
- [tubearchivist/tubearchivist](https://github.com/tubearchivist/tubearchivist): Your self hosted YouTube media server
- [paperless-ngx/paperless-ngx](https://github.com/paperless-ngx/paperless-ngx): A community-supported supercharged document management system: scan, index and archive all your documents

Concrete lessons worth investigating:

- Tube Archivist: metadata indexing and playlist lifecycle. Syllaro keeps
  transcripts while deleting downloaded media, so permanent video-library
  retention is a different product goal.
- Whisper ASR Webservice: separate CPU/GPU deployment and an ASR service boundary.
  Our separate transcription/diarization processes fit the 4 GiB memory budget.
- WhisperX: alignment and diarization fidelity; speaker labels are not names.
- Summarize: extraction before summarization, existing-caption reuse, and explicit
  provider selection. Caption reuse would need a policy for speaker attribution.
- Paperless-ngx: investigate its document-ingestion lifecycle for durable
  completion, duplicate handling, and searchable derived artifacts. This is
  a proposed design analogy, not an audited account of its implementation.

For Syllaro, the next architectural pressure points are video-ID deduplication,
per-stage retry/backoff, and transcript provenance. Keep the single-host queue
until concurrency or volume actually calls for a database/task broker.
