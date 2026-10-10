<script lang="ts">
    import { onMount } from 'svelte';
    import { Button } from '$lib/components/ui/button';
    import { Input } from '$lib/components/ui/input';
    import { Label } from '$lib/components/ui/label';
    import { Badge } from '$lib/components/ui/badge';
    import * as Card from '$lib/components/ui/card';
    import * as Alert from '$lib/components/ui/alert';
    import * as Tabs from '$lib/components/ui/tabs';
    import * as NativeSelect from '$lib/components/ui/native-select';
    import { ScrollArea } from '$lib/components/ui/scroll-area';
    import { Separator } from '$lib/components/ui/separator';
    import DOMPurify from 'dompurify';
    import { marked } from 'marked';
    import {
        request,
        jobPath,
        artifactPath,
        type Job,
        type JobList,
        type Artifact,
        type Submission,
    } from './lib/api/client';
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
    let artifactTab = $state('transcript');
    const active = $derived(
        jobs.some((job) =>
            ['pending', 'running', 'summarizing'].includes(job.status),
        ),
    );
    const counts = $derived(
        jobs.reduce<Record<string, number>>((result, job) => {
            result[job.status] = (result[job.status] || 0) + 1;
            return result;
        }, {}),
    );
    const date = (value?: number | null) =>
        value ? new Date(value * 1000).toLocaleString() : 'Not recorded';
    const markdown = (content: string) =>
        DOMPurify.sanitize(marked.parse(content, { async: false }));
    async function details(job: Job) {
        const token = ++generation;
        const changed =
            selected?.id !== job.id || selected?.queue !== job.queue;
        selected = job;
        if (changed) {
            contents = {};
            artifactTab = job.artifacts[0] || 'transcript';
        }
        detailError = '';
        try {
            const current = await request<Job>(jobPath(job));
            const entries = await Promise.all(
                current.artifacts.map(
                    async (name) =>
                        [
                            name,
                            await request<Artifact>(
                                artifactPath(current, name),
                            ),
                        ] as const,
                ),
            );
            if (token !== generation) return;
            selected = current;
            contents = Object.fromEntries(entries);
        } catch (e) {
            if (token === generation)
                detailError = String(e instanceof Error ? e.message : e);
        }
    }
    async function refresh() {
        if (refreshing) return;
        refreshing = true;
        try {
            const result = await request<JobList>('/jobs');
            jobs = result.jobs;
            queues = result.queues;
            invalid = result.invalid_records;
            lastUpdated = new Date().toLocaleTimeString();
            error = '';
            if (selected) {
                const current = jobs.find(
                    (job) =>
                        job.id === selected?.id &&
                        job.queue === selected?.queue,
                );
                if (current) await details(current);
            }
        } catch (e) {
            error = String(e instanceof Error ? e.message : e);
        } finally {
            refreshing = false;
        }
    }
    async function submit(event: SubmitEvent) {
        event.preventDefault();
        try {
            const url = new URL(source.trim());
            if (
                !['http:', 'https:'].includes(url.protocol) ||
                ![
                    'youtube.com',
                    'www.youtube.com',
                    'm.youtube.com',
                    'youtu.be',
                ].includes(url.hostname) ||
                url.username ||
                url.password
            )
                throw new Error('Enter an HTTP(S) YouTube URL');
        } catch {
            error = 'Enter an HTTP(S) YouTube URL';
            return;
        }
        submitting = true;
        notice = '';
        try {
            const body: Submission = {
                source: source.trim(),
                profile: 'local',
            };
            const job = await request<Job>(
                `/jobs?queue=${encodeURIComponent(queue)}`,
                body,
            );
            source = '';
            notice =
                'Queued. An existing worker will pick this up on its next pass.';
            await refresh();
            await details(job);
        } catch (e) {
            error = String(e instanceof Error ? e.message : e);
        } finally {
            submitting = false;
        }
    }
    async function retry() {
        if (!selected) return;
        retrying = true;
        try {
            const job = await request<Job>(
                jobPath(selected).replace('?', '/retry?'),
                {},
            );
            notice = 'Retry queued using the existing lifecycle.';
            await refresh();
            await details(job);
        } catch (e) {
            detailError = String(e instanceof Error ? e.message : e);
        } finally {
            retrying = false;
        }
    }
    onMount(() => {
        void refresh();
        const timer = setInterval(() => {
            if (active || error) void refresh();
        }, 5000);
        return () => {
            clearInterval(timer);
            generation++;
        };
    });
</script>

<div class="mx-auto max-w-7xl px-4 py-8 sm:px-8">
    <header class="mb-8 flex flex-wrap items-center justify-between gap-4">
        <div>
            <p class="mb-1 text-xs font-semibold tracking-widest text-primary">
                LOCAL MEDIA WORKSPACE
            </p>
            <h1 class="text-4xl font-bold tracking-tight">Syllaro</h1>
            <p class="mt-2 text-muted-foreground">
                From source to speech to useful next steps.
            </p>
        </div>
        <div class="flex items-center gap-3">
            <span class="text-sm text-muted-foreground" aria-live="polite"
                >{lastUpdated ? `Updated ${lastUpdated}` : 'Connecting…'}</span
            >
            <Button variant="outline" onclick={refresh} disabled={refreshing}
                >Refresh</Button
            >
        </div>
    </header>

    <Card.Root class="mb-6">
        <Card.Content>
            <form onsubmit={submit} class="flex flex-wrap items-end gap-3">
                <div class="min-w-48 flex-1 space-y-2">
                    <Label for="source">YouTube source</Label>
                    <Input
                        id="source"
                        type="url"
                        bind:value={source}
                        placeholder="https://youtu.be/…"
                        required
                        maxlength={2048}
                    />
                </div>
                <div class="space-y-2">
                    <Label for="queue">Queue</Label>
                    <NativeSelect.Root id="queue" bind:value={queue}>
                        {#each queues as name}<NativeSelect.Option value={name}
                                >{name}</NativeSelect.Option
                            >{/each}
                    </NativeSelect.Root>
                </div>
                <Button type="submit" disabled={submitting}
                    >{submitting ? 'Submitting…' : 'Add to queue'}</Button
                >
                <p class="w-full text-sm text-muted-foreground">
                    Submission saves a job. Processing stays with your existing
                    CLI workers.
                </p>
            </form>
        </Card.Content>
    </Card.Root>
    {#if error}<Alert.Root variant="destructive" class="mb-4"
            ><Alert.Description>{error}</Alert.Description></Alert.Root
        >{/if}
    {#if notice}<Alert.Root role="status" class="mb-4"
            ><Alert.Description>{notice}</Alert.Description></Alert.Root
        >{/if}
    {#if invalid}<Alert.Root variant="destructive" class="mb-4"
            ><Alert.Description
                >{invalid} invalid queue record(s) could not be shown. The list is
                incomplete.</Alert.Description
            ></Alert.Root
        >{/if}

    <div class="mb-6 flex flex-wrap gap-2" aria-label="Queue state counts">
        {#each Object.entries(counts) as [state, count]}<Badge
                variant={state === 'failed' ? 'destructive' : 'secondary'}
                >{state} <strong>{count}</strong></Badge
            >{/each}
    </div>
    <main class="grid items-start gap-6 lg:grid-cols-[22rem_1fr]">
        <Card.Root class="min-w-0 gap-4">
            <Card.Header class="flex flex-row items-center justify-between"
                ><Card.Title>Jobs</Card.Title><span
                    class="text-muted-foreground">{jobs.length}</span
                ></Card.Header
            >
            <Card.Content>
                {#if !jobs.length}<p class="text-muted-foreground">
                        No jobs yet. Submit a YouTube URL above.
                    </p>{/if}
                <ScrollArea class="h-[60vh] lg:h-[68vh]">
                    <div class="space-y-2 pr-3">
                        {#each jobs as job (`${job.queue}/${job.id}`)}
                            <Button
                                variant="ghost"
                                class={`job h-auto w-full items-start justify-start whitespace-normal p-3 text-left ${selected?.id === job.id && selected?.queue === job.queue ? 'bg-accent ring-1 ring-primary/40' : ''}`}
                                aria-pressed={selected?.id === job.id &&
                                    selected?.queue === job.queue}
                                onclick={() => details(job)}
                            >
                                <span
                                    class="flex min-w-0 flex-col items-start gap-2"
                                >
                                    <span class="break-words font-medium"
                                        >{job.title}</span
                                    >
                                    <span class="text-xs text-muted-foreground"
                                        >{job.queue} · {date(job.created)}</span
                                    >
                                    <Badge
                                        variant={job.status === 'failed'
                                            ? 'destructive'
                                            : 'secondary'}
                                        >{job.status}{job.status === 'failed'
                                            ? ' · error'
                                            : ''}</Badge
                                    >
                                </span>
                            </Button>
                        {/each}
                    </div>
                </ScrollArea>
            </Card.Content>
        </Card.Root>
        <Card.Root class="min-w-0" aria-live="polite">
            {#if selected}
                <Card.Header>
                    <Card.Description
                        >{selected.queue} / {selected.kind}</Card.Description
                    >
                    <Card.Title class="break-words text-xl"
                        >{selected.title}</Card.Title
                    >
                </Card.Header>
                <Card.Content class="space-y-5">
                    <dl class="grid grid-cols-[5rem_1fr] gap-3 text-sm">
                        <dt class="text-muted-foreground">Status</dt>
                        <dd>
                            {selected.status}{selected.stage
                                ? ` · ${selected.stage}`
                                : ''}
                        </dd>
                        <dt class="text-muted-foreground">Created</dt>
                        <dd>{date(selected.created)}</dd>
                        <dt class="text-muted-foreground">Profile</dt>
                        <dd>{selected.profile}</dd>
                        <dt class="text-muted-foreground">Source</dt>
                        <dd class="break-all">{selected.source}</dd>
                        <dt class="text-muted-foreground">Job ID</dt>
                        <dd class="break-all">{selected.id}</dd>
                    </dl>
                    {#if selected.error}<Alert.Root variant="destructive"
                            ><Alert.Description class="break-all"
                                >{selected.error}</Alert.Description
                            ></Alert.Root
                        >{/if}
                    {#if selected.status === 'failed'}<Button
                            variant="outline"
                            onclick={retry}
                            disabled={retrying}
                            >{retrying
                                ? 'Retrying…'
                                : 'Retry failed job'}</Button
                        >{/if}
                    {#if detailError}<Alert.Root variant="destructive"
                            ><Alert.Description>{detailError}</Alert.Description
                            ></Alert.Root
                        >{/if}
                    {#if selected.artifacts.length}
                        <Separator />
                        <Tabs.Root bind:value={artifactTab}>
                            <Tabs.List
                                class="flex h-auto flex-wrap"
                                aria-label="Job artifacts"
                            >
                                {#each selected.artifacts as name}<Tabs.Trigger
                                        value={name}
                                        >{name === 'action-items'
                                            ? 'Action items'
                                            : name === 'briefing'
                                              ? 'Briefing'
                                              : 'Transcript'}</Tabs.Trigger
                                    >{/each}
                            </Tabs.List>
                            {#each selected.artifacts as name}
                                <Tabs.Content value={name} class="mt-4">
                                    {#if contents[name]}
                                        {#if contents[name].format === 'text'}<pre
                                                class="max-h-[70vh] overflow-auto whitespace-pre-wrap break-words text-sm leading-relaxed">{contents[
                                                    name
                                                ].content}</pre>
                                        {:else}<div class="markdown">
                                                {@html markdown(
                                                    contents[name].content,
                                                )}
                                            </div>{/if}
                                    {:else}<p
                                            class="text-sm text-muted-foreground"
                                        >
                                            Loading artifact…
                                        </p>{/if}
                                </Tabs.Content>
                            {/each}
                        </Tabs.Root>
                    {:else}<p class="text-muted-foreground">
                            Artifacts will appear after the worker generates
                            them.
                        </p>{/if}
                </Card.Content>
            {:else}
                <Card.Content
                    class="grid min-h-80 content-center gap-2 text-center"
                    ><h2 class="text-lg font-semibold">Select a job</h2>
                    <p class="text-muted-foreground">
                        Inspect its state, transcript and briefing here.
                    </p></Card.Content
                >
            {/if}
        </Card.Root>
    </main>
    <footer class="mt-6 text-sm text-muted-foreground">
        {active
            ? 'Polling active queues every 5 seconds.'
            : 'Queue idle. Use Refresh to check for external changes.'} Transcribed
        jobs may await a separate summarization run.
    </footer>
</div>
