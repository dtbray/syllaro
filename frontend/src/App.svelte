<script lang="ts">
  import { onMount } from 'svelte';
  import DOMPurify from 'dompurify';
  import { marked } from 'marked';
  import { request, jobPath, artifactPath, type Job, type JobList, type Artifact, type Submission } from './lib/api/client';
  let jobs = $state<Job[]>([]);
  let queues = $state<string[]>(['main']);
  let queue = $state('main');
  let source = $state('');
  let selected = $state<Job | null>(null);
  let contents = $state<Record<string, Artifact>>({});
  let error = $state('');
  let detailError = $state('');
  let notice = $state('');
  let invalid = $state(0);
  let refreshing = $state(false);
  let submitting = $state(false);
  let retrying = $state(false);
  let lastUpdated = $state('');
  let generation = 0;
  const active = $derived(jobs.some(job => ['pending', 'running', 'summarizing'].includes(job.status)));
  const counts = $derived(jobs.reduce<Record<string, number>>((result, job) => { result[job.status] = (result[job.status] || 0) + 1; return result; }, {}));
  const date = (value?: number | null) => value ? new Date(value * 1000).toLocaleString() : 'Not recorded';
  const markdown = (content: string) => DOMPurify.sanitize(marked.parse(content, { async: false }));
  async function details(job: Job) {
    const token = ++generation;
    const changed = selected?.id !== job.id || selected?.queue !== job.queue;
    selected = job;
    if (changed) contents = {};
    detailError = '';
    try {
      const current = await request<Job>(jobPath(job));
      const entries = await Promise.all(current.artifacts.map(async name => [name, await request<Artifact>(artifactPath(current, name))] as const));
      if (token !== generation) return;
      selected = current;
      contents = Object.fromEntries(entries);
    } catch (e) { if (token === generation) detailError = String(e instanceof Error ? e.message : e); }
  }
  async function refresh() {
    if (refreshing) return;
    refreshing = true;
    try {
      const result = await request<JobList>('/jobs');
      jobs = result.jobs; queues = result.queues; invalid = result.invalid_records;
      lastUpdated = new Date().toLocaleTimeString(); error = '';
      if (selected) {
        const current = jobs.find(job => job.id === selected?.id && job.queue === selected?.queue);
        if (current) await details(current);
      }
    } catch (e) { error = String(e instanceof Error ? e.message : e); }
    finally { refreshing = false; }
  }
  async function submit(event: SubmitEvent) {
    event.preventDefault();
    try {
      const url = new URL(source.trim());
      if (!['http:', 'https:'].includes(url.protocol) || !['youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be'].includes(url.hostname) || url.username || url.password) throw new Error('Enter an HTTP(S) YouTube URL');
    } catch { error = 'Enter an HTTP(S) YouTube URL'; return; }
    submitting = true; notice = '';
    try {
      const body: Submission = { source: source.trim(), profile: 'local' };
      const job = await request<Job>(`/jobs?queue=${encodeURIComponent(queue)}`, body);
      source = ''; notice = 'Queued. An existing worker will pick this up on its next pass.';
      await refresh(); await details(job);
    } catch (e) { error = String(e instanceof Error ? e.message : e); }
    finally { submitting = false; }
  }
  async function retry() {
    if (!selected) return;
    retrying = true;
    try {
      const job = await request<Job>(jobPath(selected).replace('?', '/retry?'), {});
      notice = 'Retry queued using the existing lifecycle.';
      await refresh(); await details(job);
    } catch (e) { detailError = String(e instanceof Error ? e.message : e); }
    finally { retrying = false; }
  }
  onMount(() => {
    void refresh();
    const timer = setInterval(() => { if (active || error) void refresh(); }, 5000);
    return () => { clearInterval(timer); generation++; };
  });
</script>

<div class="mx-auto max-w-7xl px-4 py-8 sm:px-8">
  <header class="mb-8 flex flex-wrap items-center justify-between gap-4">
    <div><p class="eyebrow">LOCAL MEDIA WORKSPACE</p><h1>Syllaro</h1><p class="muted">From source to speech to useful next steps.</p></div>
    <div class="flex items-center gap-3"><span class="muted text-sm" aria-live="polite">{lastUpdated ? `Updated ${lastUpdated}` : 'Connecting…'}</span><button onclick={refresh} disabled={refreshing}>Refresh</button></div>
  </header>
  <form onsubmit={submit} class="panel mb-6 flex flex-wrap items-end gap-3">
    <label class="min-w-48 flex-1">YouTube source<input type="url" bind:value={source} placeholder="https://youtu.be/…" required maxlength="2048" /></label>
    <label>Queue<select bind:value={queue}>{#each queues as name}<option value={name}>{name}</option>{/each}</select></label>
    <button class="primary" type="submit" disabled={submitting}>{submitting ? 'Submitting…' : 'Add to queue'}</button>
    <p class="muted w-full text-sm">Submission saves a job. Processing stays with your existing CLI workers.</p>
  </form>
  {#if error}<p class="alert" role="alert">{error}</p>{/if}
  {#if notice}<p class="notice" role="status">{notice}</p>{/if}
  {#if invalid}<p class="alert">{invalid} invalid queue record(s) could not be shown. The list is incomplete.</p>{/if}
  <div class="mb-6 flex flex-wrap gap-2" aria-label="Queue state counts">
    {#each Object.entries(counts) as [state, count]}<span class="badge">{state} <strong>{count}</strong></span>{/each}
  </div>
  <main class="grid gap-6 lg:grid-cols-[22rem_1fr]">
    <section class="panel jobs"><div class="mb-4 flex justify-between"><h2>Jobs</h2><span class="muted">{jobs.length}</span></div>
      {#if !jobs.length}<p class="muted">No jobs yet. Submit a YouTube URL above.</p>{/if}
      <div class="job-list">{#each jobs as job (`${job.queue}/${job.id}`)}
        <button class:selected={selected?.id === job.id && selected?.queue === job.queue} class="job" onclick={() => details(job)}>
          <span class="job-title">{job.title}</span><span class="muted text-xs">{job.queue} · {date(job.created)}</span>
          <span class:failed={job.status === 'failed'} class="badge">{job.status}{job.status === 'failed' ? ' · error' : ''}</span>
        </button>
      {/each}</div>
    </section>
    <section class="panel min-w-0" aria-live="polite">
      {#if selected}
        <p class="eyebrow">{selected.queue} / {selected.kind}</p><h2 class="break-words text-xl">{selected.title}</h2>
        <dl class="metadata"><dt>Status</dt><dd>{selected.status}{selected.stage ? ` · ${selected.stage}` : ''}</dd><dt>Created</dt><dd>{date(selected.created)}</dd><dt>Profile</dt><dd>{selected.profile}</dd><dt>Source</dt><dd class="break-all">{selected.source}</dd><dt>Job ID</dt><dd class="break-all">{selected.id}</dd></dl>
        {#if selected.error}<p class="alert">{selected.error}</p>{/if}
        {#if selected.status === 'failed'}<button onclick={retry} disabled={retrying}>{retrying ? 'Retrying…' : 'Retry failed job'}</button>{/if}
        {#if detailError}<p class="alert" role="alert">{detailError}</p>{/if}
        {#each ['transcript', 'briefing', 'action-items'] as name}
          {#if contents[name]}<details open={name !== 'transcript'}><summary>{name === 'action-items' ? 'Action items' : name === 'briefing' ? 'Briefing' : 'Transcript'}</summary>
            {#if contents[name].format === 'text'}<pre>{contents[name].content}</pre>{:else}<div class="markdown">{@html markdown(contents[name].content)}</div>{/if}
          </details>{/if}
        {/each}
        {#if !selected.artifacts.length}<p class="muted mt-6">Artifacts will appear after the worker generates them.</p>{/if}
      {:else}<div class="empty"><h2>Select a job</h2><p class="muted">Inspect its state, transcript and briefing here.</p></div>{/if}
    </section>
  </main>
  <footer class="muted mt-6 text-sm">{active ? 'Polling active queues every 5 seconds.' : 'Queue idle. Use Refresh to check for external changes.'} Transcribed jobs may await a separate summarization run.</footer>
</div>
