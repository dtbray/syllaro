# Explicit workstation speech processing

The tested deployment retains downloads and durable job/artifact ownership on the
laptop and routes pending transcription/diarization to a single explicit workstation.
Machine-specific scripts, service units and dated benchmark evidence live in the
Homelab repository under `ops/hardware/pop-os/handoff/`. Installed laptop scripts
live at `~/.local/share/syllaro-runtime/workstation-handoff/`.

This is operational tooling around the core worker, not a portable SSH backend.
It requires the tested source/destination Syllaro API and an explicitly configured
SSH destination with pinned local models. No automatic remote or paid fallback is
enabled. RSS ingestion is not implemented by this handoff.

The laptop coordinator holds the core queue's exclusive `worker.lock` while it
downloads cached audio, transfers it and validates returned aligned/diarized JSON.
The workstation gets an isolated synthetic job and verified audio checksum, not
production queue state, configuration profiles, cookies, credentials or private
model files. Generic speaker labels and model timestamps remain evidence, not
identity claims. Untimed words can remain in the transcript; invalid timed words,
empty alignment and incomplete diarization are rejected.

The source persists/syncs returned JSON and text through the core ingest finalizer
before deleting cached audio and marking the job `transcribed`. Transfer failures
retain source audio; completed remote receipts permit recovery without repeated
inference. Completed source jobs are preserved. Failed jobs require explicit retry.
Summary-ready jobs are not claimed by this ingestion-only coordinator.

On the tested RX 9060 XT 16 GB/Pop!_OS workstation, the explicit Transformers
Whisper-small/ROCm route uses float16 ASR, CPU WhisperX word alignment and local
GPU community-1 diarization. ASR batch 1 and diarization batch 16 were selected.
Experimental ROCm attention is scoped to each explicit remote invocation; default
activation remains unchanged. CTranslate2 HIP and distilled models were rejected
after real-media failures or worse accuracy/invalid timestamps.

A matched 17.5-minute AMI meeting completed in 2:52 on the workstation versus
4:46 on the laptop, with similar exploratory reference accuracy. A 19-minute Rising
Tide notes walkthrough completed in 7:28, including 5:08 CPU alignment. Continuous
speech therefore needs further alignment tuning; do not generalize the AMI speedup
to every recording. That walkthrough passed structural validation and transcript
spot checks, but has no human reference word/diarization error score.

The live handoff round trip and recovery were validated separately from model
benchmarks and mocked failure/locking tests. The existing source job metadata was
unchanged after initial polling. Job status is authoritative: a successful CLI or
service exit alone does not imply every claimed job succeeded.

```sh
systemctl --user status syllaro-ingest.timer
journalctl --user -u syllaro-ingest.service -n 40 --no-pager
# Stop polling, then let an active handoff finish before changing routing:
systemctl --user stop syllaro-ingest.timer
```

Future RSS intake should retain feed/item GUID and enclosure provenance and enqueue
durable cached media through an explicit media source type. Audio processing and
summarization remain separate stages; this deployment does not invoke cloud models.
