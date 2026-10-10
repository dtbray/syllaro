<script lang="ts">
    import { onMount, tick, untrack } from 'svelte';
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
    let formError = $state('');
    let detailError = $state('');
    let artifactErrors = $state<Record<string, string>>({});
    let artifactLoading = $state<Record<string, boolean>>({});
    let queueFilter = $state('');
    let mobileDetail = $state(false);
    let statusMessage = $state('');
    let jobGeneration = 0;
    let listScroll = 0;
    let selectedButton: HTMLButtonElement | null = null;
    let detailHeading = $state<HTMLHeadingElement | null>(null);
    let artifactEpoch = 0;
    let detailRequest = 0;
    let cacheVersion = $state(0);
    let loadedVersions: Record<string, number> = {};
    let cachedSignature = '';
    let listContainer: HTMLElement | null = null;
    let notice = $state('');
    let invalid = $state(0);
    let refreshing = $state(false);
    let submitting = $state(false);
    let retrying = $state(false);
    let lastUpdated = $state('');
    let live = $state(false);
    type Change = { queue: string; id: string; artifact: boolean };
    let pendingChanges: Change[] = [];
    let pendingReset = false;
    let artifactTab = $state('transcript');
    const STATUS_ORDER = [
        'pending',
        'running',
        'transcribed',
        'summarizing',
        'done',
        'failed',
    ];
    const statusLabel = (status: string) =>
        status === 'done'
            ? 'Complete'
            : status
                  .split('-')
                  .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
                  .join(' ');
    const filteredJobs = $derived(
        queueFilter === ''
            ? jobs
            : jobs.filter((job) => job.queue === queueFilter),
    );
    const counts = $derived(
        STATUS_ORDER.map(
            (status) =>
                [
                    status,
                    jobs.filter((job) => job.status === status).length,
                ] as const,
        ),
    );
    const artifactSignature = (job: Job | null) =>
        job
            ? `${job.queue}/${job.id}|${job.status}|${job.stage ?? ''}|${job.artifacts.join(',')}`
            : '';
    const date = (value?: number | null) =>
        value ? new Date(value * 1000).toLocaleString() : 'Not recorded';
    const markdown = (content: string) =>
        DOMPurify.sanitize(marked.parse(content, { async: false }));
    const sameJob = (
        a: Pick<Job, 'id' | 'queue'> | null,
        b: Pick<Job, 'id' | 'queue'>,
    ) => a?.id === b.id && a?.queue === b.queue;
    function invalidateArtifacts() {
        ++artifactEpoch;
        ++cacheVersion;
        loadedVersions = {};
        artifactLoading = {};
        artifactErrors = {};
    }
    async function loadArtifact(name: string, force = false) {
        const job = selected;
        if (!job || !job.artifacts.includes(name) || artifactLoading[name])
            return;
        if (
            !force &&
            (loadedVersions[name] === cacheVersion || artifactErrors[name])
        )
            return;
        const epoch = artifactEpoch;
        const version = cacheVersion;
        artifactLoading = { ...artifactLoading, [name]: true };
        artifactErrors = { ...artifactErrors, [name]: '' };
        try {
            const data = await request<Artifact>(artifactPath(job, name));
            if (epoch !== artifactEpoch || !sameJob(selected, job)) return;
            contents = { ...contents, [name]: data };
            loadedVersions[name] = version;
        } catch (e) {
            if (epoch !== artifactEpoch || !sameJob(selected, job)) return;
            artifactErrors = {
                ...artifactErrors,
                [name]: String(e instanceof Error ? e.message : e),
            };
        } finally {
            if (epoch === artifactEpoch && sameJob(selected, job))
                artifactLoading = { ...artifactLoading, [name]: false };
        }
    }
    async function updateDetails(job: Job, force = false) {
        const gen = jobGeneration;
        const token = ++detailRequest;
        try {
            const fresh = await request<Job>(jobPath(job));
            if (
                gen !== jobGeneration ||
                token !== detailRequest ||
                !sameJob(selected, job)
            )
                return;
            const signature = artifactSignature(fresh);
            selected = fresh;
            detailError = '';
            if (force || signature !== cachedSignature) {
                cachedSignature = signature;
                invalidateArtifacts();
            }
            if (!fresh.artifacts.includes(artifactTab))
                artifactTab = fresh.artifacts[0] || 'transcript';
            statusMessage = `${fresh.title}: ${statusLabel(fresh.status)}${fresh.stage ? `, ${fresh.stage}` : ''}`;
        } catch (e) {
            if (
                gen === jobGeneration &&
                token === detailRequest &&
                sameJob(selected, job)
            )
                detailError = String(e instanceof Error ? e.message : e);
        }
    }
    async function details(job: Job, button?: HTMLButtonElement) {
        if (button) selectedButton = button;
        const viewport = listContainer?.querySelector<HTMLElement>(
            '[data-slot="scroll-area-viewport"]',
        );
        if (viewport) listScroll = viewport.scrollTop;
        const changed = !sameJob(selected, job);
        ++jobGeneration;
        if (changed) {
            invalidateArtifacts();
            contents = {};
            cachedSignature = artifactSignature(job);
            artifactTab = job.artifacts[0] || 'transcript';
        }
        selected = job;
        detailError = '';
        mobileDetail = true;
        await tick();
        if (window.matchMedia('(max-width: 1023px)').matches)
            detailHeading?.focus();
        await updateDetails(job);
    }
    async function backToJobs() {
        mobileDetail = false;
        await tick();
        const viewport = listContainer?.querySelector<HTMLElement>(
            '[data-slot="scroll-area-viewport"]',
        );
        if (viewport) viewport.scrollTop = listScroll;
        const button = selected
            ? document.getElementById(`job-${selected.queue}-${selected.id}`)
            : null;
        (
            button ||
            document.getElementById('queue-filter') ||
            selectedButton
        )?.focus({ preventScroll: true });
    }
    async function skipToDetails(event: MouseEvent) {
        event.preventDefault();
        if (selected) mobileDetail = true;
        await tick();
        document
            .getElementById(selected ? 'job-details' : 'queue-filter')
            ?.focus();
    }
    async function refresh(forceArtifacts = false, changes?: Change[]) {
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
                const current = jobs.find((job) => sameJob(selected, job));
                if (current) {
                    const change = changes?.find((item) =>
                        sameJob(current, item),
                    );
                    if (!changes || change)
                        await updateDetails(
                            current,
                            forceArtifacts || !!change?.artifact,
                        );
                } else {
                    ++jobGeneration;
                    invalidateArtifacts();
                    selected = null;
                    contents = {};
                    cachedSignature = '';
                    mobileDetail = false;
                }
            }
        } catch (e) {
            error = String(e instanceof Error ? e.message : e);
        } finally {
            refreshing = false;
            if (pendingReset || pendingChanges.length) void flushChanges();
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
            formError = 'Enter an HTTP(S) YouTube URL';
            return;
        }
        formError = '';
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
            formError = String(e instanceof Error ? e.message : e);
        } finally {
            submitting = false;
        }
    }
    async function retry() {
        if (!selected) return;
        const target = selected;
        const gen = jobGeneration;
        retrying = true;
        try {
            const job = await request<Job>(
                jobPath(target).replace('?', '/retry?'),
                {},
            );
            if (gen !== jobGeneration || !sameJob(selected, target)) return;
            notice = 'Retry queued using the existing lifecycle.';
            await refresh();
            await details(job);
        } catch (e) {
            if (gen === jobGeneration && sameJob(selected, target))
                detailError = String(e instanceof Error ? e.message : e);
        } finally {
            retrying = false;
        }
    }
    async function flushChanges() {
        if (refreshing) return;
        const reset = pendingReset;
        const changes = pendingChanges;
        pendingReset = false;
        pendingChanges = [];
        await refresh(reset, reset ? undefined : changes);
    }
    onMount(() => {
        const events = new EventSource('/api/v1/events');
        events.addEventListener('change', (event) => {
            const message = JSON.parse((event as MessageEvent).data) as {
                reset: boolean;
                changes: Change[];
            };
            live = true;
            pendingReset ||= message.reset;
            for (const change of message.changes) {
                const previous = pendingChanges.find((item) =>
                    sameJob(item, change),
                );
                if (previous) previous.artifact ||= change.artifact;
                else pendingChanges.push(change);
            }
            if (pendingChanges.length > 1024) {
                pendingChanges = [];
                pendingReset = true;
            }
            void flushChanges();
        });
        events.onerror = () => {
            live = false;
        };
        void refresh();
        return () => {
            events.close();
            ++jobGeneration;
            ++detailRequest;
            ++artifactEpoch;
        };
    });

    $effect(() => {
        const job = selected;
        const tab = artifactTab;
        const version = cacheVersion;
        untrack(() => {
            if (job?.artifacts.includes(tab)) void loadArtifact(tab);
        });
        void version;
    });
</script>

<div class="mx-auto max-w-7xl px-4 py-6 sm:px-8">
    <a
        href="#job-details"
        onclick={skipToDetails}
        class="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-background focus:px-3 focus:py-2 focus:ring-2 focus:ring-ring"
        >Skip to job details</a
    >
    <header
        class="mb-6 flex flex-wrap items-center justify-between gap-3 border-b pb-4"
    >
        <div class="flex items-baseline gap-3">
            <h1 class="text-xl font-semibold tracking-tight">Syllaro</h1>
            <p class="text-sm text-muted-foreground">Local media workspace</p>
        </div>
        <div class="flex items-center gap-3">
            <span class="text-sm text-muted-foreground"
                >{lastUpdated ? `Updated ${lastUpdated}` : 'Connecting…'}</span
            >
            <Button
                variant="outline"
                size="sm"
                onclick={() => void refresh(true)}
                disabled={refreshing}>Refresh</Button
            >
        </div>
    </header>
    <p class="sr-only" aria-live="polite">{statusMessage}</p>

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
    {#if formError}<Alert.Root variant="destructive" class="mb-4"
            ><Alert.Description>{formError}</Alert.Description></Alert.Root
        >{/if}
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

    <div
        class="mb-6 flex flex-wrap gap-2 tabular-nums"
        aria-label="Queue state counts"
    >
        {#each counts as [state, count]}
            <Badge
                class={count === 0 ? 'text-muted-foreground' : ''}
                variant={state === 'failed' && count > 0
                    ? 'destructive'
                    : 'secondary'}
                >{statusLabel(state)} <strong>{count}</strong></Badge
            >
        {/each}
    </div>
    <main class="grid items-start gap-6 lg:grid-cols-[22rem_1fr]">
        <Card.Root
            class={`min-w-0 gap-4 ${mobileDetail ? 'hidden lg:flex' : ''}`}
        >
            <div class="px-6 space-y-2">
                <Label for="queue-filter">Show jobs from</Label>
                <NativeSelect.Root id="queue-filter" bind:value={queueFilter}>
                    <NativeSelect.Option value=""
                        >All queues</NativeSelect.Option
                    >
                    {#each queues as name}<NativeSelect.Option value={name}
                            >{name}</NativeSelect.Option
                        >{/each}
                </NativeSelect.Root>
            </div>
            <Card.Header class="flex flex-row items-center justify-between"
                ><Card.Title>Jobs</Card.Title><span
                    class="text-muted-foreground">{filteredJobs.length}</span
                ></Card.Header
            >
            <Card.Content>
                {#if !filteredJobs.length}<p class="text-muted-foreground">
                        No jobs in this view. Submit a YouTube URL above or
                        choose another queue.
                    </p>{/if}
                <div bind:this={listContainer}>
                    <ScrollArea class="h-[60vh] lg:h-[68vh]">
                        <div class="space-y-2 pr-3">
                            {#each filteredJobs as job (`${job.queue}/${job.id}`)}
                                <Button
                                    variant="ghost"
                                    class={`job h-auto w-full items-start justify-start whitespace-normal p-3 text-left ${selected?.id === job.id && selected?.queue === job.queue ? 'job-selected' : ''}`}
                                    aria-pressed={selected?.id === job.id &&
                                        selected?.queue === job.queue}
                                    id={`job-${job.queue}-${job.id}`}
                                    onclick={(e) =>
                                        details(
                                            job,
                                            e.currentTarget as HTMLButtonElement,
                                        )}
                                >
                                    <span
                                        class="flex min-w-0 flex-col items-start gap-2"
                                    >
                                        <span class="break-words font-medium"
                                            >{job.title}</span
                                        >
                                        <span
                                            class="text-xs text-muted-foreground tabular-nums"
                                            >{job.queue} · {date(
                                                job.created,
                                            )}</span
                                        >
                                        <Badge
                                            variant={job.status === 'failed'
                                                ? 'destructive'
                                                : 'secondary'}
                                            >{statusLabel(
                                                job.status,
                                            )}{job.status === 'failed'
                                                ? ' · error'
                                                : ''}</Badge
                                        >
                                    </span>
                                </Button>
                            {/each}
                        </div>
                    </ScrollArea>
                </div>
            </Card.Content>
        </Card.Root>
        <Card.Root
            class={`min-w-0 ${mobileDetail ? '' : 'hidden lg:flex'}`}
            id="job-details"
            tabindex={-1}
        >
            {#if selected}
                <Card.Header>
                    <Button
                        variant="ghost"
                        class="mb-2 lg:hidden"
                        onclick={() => void backToJobs()}>← Back to jobs</Button
                    >
                    <Card.Description
                        >{selected.queue} / {selected.kind}</Card.Description
                    >
                    <h2
                        bind:this={detailHeading}
                        id="job-detail-heading"
                        tabindex="-1"
                        class="break-words text-xl font-semibold tracking-tight focus:outline-none focus:ring-2 focus:ring-ring rounded"
                    >
                        {selected.title}
                    </h2>
                </Card.Header>
                <Card.Content class="space-y-5">
                    <dl
                        class="grid grid-cols-[5rem_1fr] gap-3 text-sm tabular-nums"
                    >
                        <dt class="text-muted-foreground">Status</dt>
                        <dd>
                            {statusLabel(selected.status)}{selected.stage
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
                                    {#if artifactErrors[name]}
                                        <Alert.Root variant="destructive">
                                            <Alert.Description>
                                                {artifactErrors[name]}
                                                <Button
                                                    variant="outline"
                                                    size="sm"
                                                    class="ml-2"
                                                    onclick={() =>
                                                        loadArtifact(
                                                            name,
                                                            true,
                                                        )}>Retry</Button
                                                >
                                            </Alert.Description>
                                        </Alert.Root>
                                    {/if}
                                    {#if contents[name]}
                                        {#if contents[name].format === 'text'}<pre
                                                class="transcript whitespace-pre-wrap break-words text-sm leading-relaxed tabular-nums">{contents[
                                                    name
                                                ].content}</pre>
                                        {:else}<div class="markdown">
                                                {@html markdown(
                                                    contents[name].content,
                                                )}
                                            </div>{/if}
                                    {:else if artifactLoading[name]}<p
                                            class="text-sm text-muted-foreground"
                                        >
                                            Loading artifact…
                                        </p>
                                    {:else if !artifactErrors[name]}<p
                                            class="text-sm text-muted-foreground"
                                        >
                                            Artifact not loaded.
                                            <Button
                                                variant="outline"
                                                size="sm"
                                                onclick={() =>
                                                    loadArtifact(name, true)}
                                                >Load</Button
                                            >
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
        {live
            ? 'Live updates connected.'
            : 'Live updates disconnected. Reconnecting; Refresh is available.'} Transcribed
        jobs may await a separate summarization run.
    </footer>
</div>
