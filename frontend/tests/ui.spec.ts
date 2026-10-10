import { test, expect } from '@playwright/test';
const initial = {
    id: 'example',
    queue: 'main',
    title: 'Example recording',
    source: 'https://youtu.be/example',
    kind: 'youtube',
    profile: 'local',
    status: 'failed',
    created: 1700000000,
    error: 'Download failed',
    artifacts: ['transcript', 'briefing'],
};
test('select job, preserve transcript labels, sanitize briefing, and retry', async ({
    page,
}) => {
    let job = { ...initial };
    await page.route('**/api/v1/**', async (route) => {
        const path = new URL(route.request().url()).pathname;
        let body: unknown;
        if (path.endsWith('/transcript'))
            body = {
                content: '[00:12] SPEAKER_00: Review the plan.',
                format: 'text',
            };
        else if (path.endsWith('/briefing'))
            body = {
                content:
                    '## Plan\n<script>window.infected=true</script>\n<img src=x onerror="window.infected=true">\n[bad](javascript:alert(1))',
                format: 'markdown',
            };
        else if (path.endsWith('/retry')) {
            job = { ...job, status: 'pending', error: '' };
            body = job;
        } else if (path.endsWith('/jobs'))
            body = { jobs: [job], queues: ['main'], invalid_records: 0 };
        else body = job;
        await route.fulfill({ json: body });
    });
    await page.goto('/');
    await page.getByRole('button', { name: /Example recording/ }).click();
    await expect(
        page.getByText('Download failed', { exact: true }),
    ).toBeVisible();
    await page.getByRole('tab', { name: 'Transcript', exact: true }).click();
    await expect(page.locator('pre')).toContainText('[00:12] SPEAKER_00');
    await page.getByRole('tab', { name: 'Transcript', exact: true }).focus();
    await page.keyboard.press('ArrowRight');
    await expect(
        page.getByRole('tab', { name: 'Briefing', exact: true }),
    ).toHaveAttribute('aria-selected', 'true');
    await expect(page.locator('.markdown')).toBeVisible();
    await expect(page.locator('.markdown script')).toHaveCount(0);
    await expect(page.locator('.markdown [onerror]')).toHaveCount(0);
    await expect(page.locator('.markdown a[href^="javascript:"]')).toHaveCount(
        0,
    );
    expect(
        await page.evaluate(
            () => (window as unknown as Record<string, unknown>).infected,
        ),
    ).toBeUndefined();
    await page.getByRole('button', { name: 'Retry failed job' }).click();
    await expect(
        page.getByText('Retry queued using the existing lifecycle.'),
    ).toBeVisible();
});
test('submit source, show failure, and refresh without a full reload', async ({
    page,
}) => {
    let jobs: unknown[] = [];
    await page.route('**/api/v1/**', async (route) => {
        if (route.request().method() === 'POST') {
            expect(route.request().postDataJSON().source).toBe(
                'https://youtu.be/new',
            );
            const job = {
                ...initial,
                id: 'new',
                status: 'pending',
                error: null,
                artifacts: [],
            };
            jobs = [job];
            await route.fulfill({ status: 201, json: job });
        } else if (new URL(route.request().url()).pathname.endsWith('/jobs'))
            await route.fulfill({
                json: { jobs, queues: ['main'], invalid_records: 0 },
            });
        else await route.fulfill({ json: jobs[0] });
    });
    await page.goto('/');
    await page
        .getByLabel('YouTube source')
        .fill('https://example.com/not-youtube');
    await page.getByRole('button', { name: 'Add to queue' }).click();
    await expect(page.getByRole('alert')).toContainText('YouTube URL');
    await page.getByLabel('YouTube source').fill('https://youtu.be/new');
    await page.getByRole('button', { name: 'Add to queue' }).click();
    await expect(page.getByRole('status')).toContainText('Queued');
    jobs = [
        {
            ...initial,
            id: 'new',
            title: 'Worker finished',
            status: 'transcribed',
            error: null,
            artifacts: [],
        },
    ];
    await expect(
        page.getByRole('button', { name: /Worker finished/ }),
    ).toBeVisible({ timeout: 10000 });
    await page.getByRole('button', { name: 'Refresh', exact: true }).click();
    await expect(
        page.getByRole('button', { name: /Worker finished/ }),
    ).toBeVisible();
});
test('API failure is visible and manual refresh recovers', async ({ page }) => {
    let unavailable = true;
    await page.route('**/api/v1/jobs', async (route) => {
        if (unavailable)
            await route.fulfill({
                status: 500,
                json: {
                    code: 'storage_error',
                    message: 'Queue storage is unavailable',
                },
            });
        else
            await route.fulfill({
                json: { jobs: [], queues: ['main'], invalid_records: 0 },
            });
    });
    await page.goto('/');
    await expect(page.getByRole('alert')).toContainText(
        'Queue storage is unavailable',
    );
    unavailable = false;
    await page.getByRole('button', { name: 'Refresh', exact: true }).click();
    await expect(page.getByRole('alert')).toHaveCount(0);
});
const ready = { ...initial, status: 'done', error: null };
test('artifacts load lazily per tab and cache after first visit', async ({
    page,
}) => {
    const artifactRequests: string[] = [];
    await page.route('**/api/v1/**', async (route) => {
        const url = new URL(route.request().url());
        const path = url.pathname;
        if (path.endsWith('/transcript')) {
            artifactRequests.push('transcript');
            await route.fulfill({
                json: { content: 'First transcript', format: 'text' },
            });
        } else if (path.endsWith('/briefing')) {
            artifactRequests.push('briefing');
            await route.fulfill({
                json: { content: 'Second briefing', format: 'markdown' },
            });
        } else if (path.endsWith('/jobs'))
            await route.fulfill({
                json: { jobs: [ready], queues: ['main'], invalid_records: 0 },
            });
        else await route.fulfill({ json: ready });
    });
    await page.goto('/');
    await page.getByRole('button', { name: /Example recording/ }).click();
    await expect(
        page.getByRole('tab', { name: 'Transcript', exact: true }),
    ).toHaveAttribute('aria-selected', 'true');
    await expect.poll(() => artifactRequests).toEqual(['transcript']);
    await page.getByRole('tab', { name: 'Briefing', exact: true }).click();
    await expect(page.locator('.markdown')).toContainText('Second briefing');
    expect(artifactRequests).toEqual(['transcript', 'briefing']);
    await page.getByRole('tab', { name: 'Transcript', exact: true }).click();
    await expect(page.locator('pre')).toContainText('First transcript');
    await page.waitForTimeout(300);
    expect(artifactRequests).toEqual(['transcript', 'briefing']);
});
test('one artifact failure does not block the other tab and retry recovers', async ({
    page,
}) => {
    let briefingFails = true;
    await page.route('**/api/v1/**', async (route) => {
        const path = new URL(route.request().url()).pathname;
        if (path.endsWith('/transcript'))
            await route.fulfill({
                json: { content: 'Good transcript', format: 'text' },
            });
        else if (path.endsWith('/briefing')) {
            if (briefingFails)
                await route.fulfill({
                    status: 500,
                    json: {
                        code: 'storage_error',
                        message: 'Briefing missing',
                    },
                });
            else
                await route.fulfill({
                    json: { content: 'Recovered briefing', format: 'markdown' },
                });
        } else if (path.endsWith('/jobs'))
            await route.fulfill({
                json: { jobs: [ready], queues: ['main'], invalid_records: 0 },
            });
        else await route.fulfill({ json: ready });
    });
    await page.goto('/');
    await page.getByRole('button', { name: /Example recording/ }).click();
    await page.getByRole('tab', { name: 'Briefing', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('Briefing missing');
    await page.getByRole('tab', { name: 'Transcript', exact: true }).click();
    await expect(page.locator('pre')).toContainText('Good transcript');
    briefingFails = false;
    await page.getByRole('tab', { name: 'Briefing', exact: true }).click();
    await page.getByRole('button', { name: 'Retry', exact: true }).click();
    await expect(page.locator('.markdown')).toContainText('Recovered briefing');
});
test('stale job response does not overwrite a newer selection', async ({
    page,
}) => {
    const slow = { ...ready, id: 'slow', title: 'Slow job' };
    const fast = { ...ready, id: 'fast', title: 'Fast job' };
    let releaseSlow: (() => void) | undefined;
    await page.route('**/api/v1/**', async (route) => {
        const path = new URL(route.request().url()).pathname;
        if (path.endsWith('/jobs'))
            await route.fulfill({
                json: {
                    jobs: [slow, fast],
                    queues: ['main'],
                    invalid_records: 0,
                },
            });
        else if (path.endsWith('/slow'))
            await new Promise<void>((resolve) => {
                releaseSlow = () => resolve();
            }).then(async () => {
                await route.fulfill({ json: slow });
            });
        else if (path.endsWith('/fast')) await route.fulfill({ json: fast });
        else if (path.endsWith('/transcript') || path.endsWith('/briefing'))
            await route.fulfill({ json: { content: '', format: 'text' } });
        else await route.fulfill({ json: fast });
    });
    await page.goto('/');
    await page.getByRole('button', { name: /Slow job/ }).click();
    await page.getByRole('button', { name: /Fast job/ }).click();
    await expect(page.getByRole('heading', { name: 'Fast job' })).toBeVisible();
    await expect.poll(() => Boolean(releaseSlow)).toBe(true);
    releaseSlow?.();
    await page.waitForTimeout(100);
    await expect(page.getByRole('heading', { name: 'Fast job' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Slow job' })).toHaveCount(
        0,
    );
});
test('invalid URL does not start 5s polling', async ({ page }) => {
    await page.clock.install();
    let jobsCalls = 0;
    await page.route('**/api/v1/jobs', async (route) => {
        jobsCalls += 1;
        await route.fulfill({
            json: { jobs: [], queues: ['main'], invalid_records: 0 },
        });
    });
    await page.goto('/');
    await expect(
        page.getByRole('button', { name: 'Add to queue' }),
    ).toBeEnabled();
    await page.clock.fastForward(1000);
    const baseline = jobsCalls;
    await page
        .getByLabel('YouTube source')
        .fill('https://example.com/not-youtube');
    await page.getByRole('button', { name: 'Add to queue' }).click();
    await expect(page.getByRole('alert')).toContainText('YouTube URL');
    await page.clock.fastForward(10000);
    await page.waitForTimeout(100);
    expect(jobsCalls).toBe(baseline);
});
test('queue filter is independent and submission/polling cover all queues', async ({
    page,
}) => {
    const mainJob = { ...ready, id: 'm1', title: 'Main job' };
    const otherJob = {
        ...ready,
        id: 'o1',
        queue: 'other',
        title: 'Other job',
    };
    let jobsList: unknown[] = [mainJob, otherJob];
    let postCount = 0;
    let listCalls = 0;
    await page.clock.install();
    await page.route('**/api/v1/**', async (route) => {
        const url = new URL(route.request().url());
        if (
            route.request().method() === 'POST' &&
            url.pathname.endsWith('/jobs')
        ) {
            postCount += 1;
            const created = {
                ...mainJob,
                id: `p${postCount}`,
                title: `Posted ${postCount}`,
                status: 'pending',
                queue: url.searchParams.get('queue') || 'main',
                artifacts: [],
            };
            jobsList = [...jobsList, created];
            await route.fulfill({ status: 201, json: created });
        } else if (url.pathname.endsWith('/jobs')) {
            listCalls++;
            await route.fulfill({
                json: {
                    jobs: jobsList,
                    queues: ['main', 'other'],
                    invalid_records: 0,
                },
            });
        } else
            await route.fulfill({
                json: jobsList.find(
                    (job) =>
                        (job as typeof mainJob).id ===
                        url.pathname.split('/').pop(),
                ),
            });
    });
    await page.goto('/');
    await expect(page.getByRole('button', { name: /Other job/ })).toBeVisible();
    await page.getByLabel('Show jobs from').selectOption('main');
    await expect(page.getByRole('button', { name: /Other job/ })).toHaveCount(
        0,
    );
    await expect(page.getByRole('button', { name: /Main job/ })).toBeVisible();
    await page.getByLabel('Queue', { exact: true }).selectOption('other');
    await page.getByLabel('YouTube source').fill('https://youtu.be/queued');
    await page.getByRole('button', { name: 'Add to queue' }).click();
    await expect(page.getByRole('status')).toContainText('Queued');
    await expect(page.getByRole('button', { name: 'Posted 1' })).toHaveCount(0);
    const beforePoll = listCalls;
    await page.clock.fastForward(6000);
    await expect.poll(() => listCalls).toBeGreaterThan(beforePoll);
    await page
        .getByLabel('Show jobs from')
        .selectOption({ label: 'All queues' });
    await expect(page.getByRole('button', { name: /Posted 1/ })).toBeVisible();
    await expect(page.getByRole('button', { name: /Other job/ })).toBeVisible();
});
test('mobile selection and back preserve focus and transcript uses one scroll', async ({
    page,
}) => {
    const jobs = Array.from({ length: 24 }, (_, i) => ({
        ...ready,
        id: `job${i}`,
        title: `Mobile job ${i}`,
    }));
    await page.route('**/api/v1/**', async (route) => {
        const path = new URL(route.request().url()).pathname;
        if (path.endsWith('/jobs'))
            await route.fulfill({
                json: { jobs, queues: ['main'], invalid_records: 0 },
            });
        else if (path.endsWith('/transcript'))
            await route.fulfill({
                json: {
                    content: Array.from(
                        { length: 300 },
                        (_, i) => `Line ${i} of transcript`,
                    ).join('\n'),
                    format: 'text',
                },
            });
        else if (path.endsWith('/briefing'))
            await route.fulfill({
                json: { content: 'Brief', format: 'markdown' },
            });
        else
            await route.fulfill({
                json: jobs.find((job) => job.id === path.split('/').pop()),
            });
    });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/');
    const jobB = page.getByRole('button', { name: /Mobile job 23/ });
    await jobB.scrollIntoViewIfNeeded();
    const viewport = page.locator('[data-slot="scroll-area-viewport"]');
    const listPosition = await viewport.evaluate((el) => el.scrollTop);
    expect(listPosition).toBeGreaterThan(0);
    await jobB.click();
    await expect(
        page.getByRole('heading', { name: 'Mobile job 23' }),
    ).toBeVisible();
    await expect(
        page.getByRole('heading', { name: 'Mobile job 23' }),
    ).toBeFocused();
    await page.getByRole('button', { name: /Back to jobs/ }).click();
    await expect(jobB).toBeFocused();
    await expect
        .poll(() => viewport.evaluate((el) => el.scrollTop))
        .toBe(listPosition);
    await jobB.click();
    await page.getByRole('tab', { name: 'Transcript', exact: true }).click();
    const transcript = page.locator('pre');
    await transcript.scrollIntoViewIfNeeded();
    const scrollable = await transcript.evaluate((el) => {
        const parent = el.closest('[data-slot="scroll-area-viewport"]');
        return {
            windowScrollable:
                document.documentElement.scrollHeight > window.innerHeight,
            parentScrollable: parent
                ? parent.scrollHeight > parent.clientHeight
                : false,
        };
    });
    expect(scrollable.parentScrollable).toBe(false);
    expect(scrollable.windowScrollable).toBe(true);
    expect(
        await transcript.evaluate((el) => getComputedStyle(el).maxHeight),
    ).toBe('none');
});
test('status counts show zero values in order', async ({ page }) => {
    await page.route('**/api/v1/jobs', async (route) => {
        await route.fulfill({
            json: { jobs: [], queues: ['main'], invalid_records: 0 },
        });
    });
    await page.goto('/');
    const badges = page.locator('[aria-label="Queue state counts"]');
    const text = ((await badges.textContent()) ?? '').replace(/\s+/g, ' ');
    expect(text).toMatch(
        /Pending\s*0.*Running\s*0.*Transcribed\s*0.*Summarizing\s*0.*Complete\s*0.*Failed\s*0/,
    );
});

test('polling caches unchanged artifacts, lifecycle and manual refresh invalidate, failures retain content', async ({
    page,
}) => {
    await page.clock.install();
    let job = { ...ready, status: 'running', stage: 'download' };
    let detailCalls = 0;
    let artifactCalls = 0;
    let failArtifact = false;
    await page.route('**/api/v1/**', async (route) => {
        const path = new URL(route.request().url()).pathname;
        if (path.endsWith('/jobs'))
            await route.fulfill({
                json: { jobs: [job], queues: ['main'], invalid_records: 0 },
            });
        else if (path.endsWith('/transcript')) {
            artifactCalls++;
            if (failArtifact)
                await route.fulfill({
                    status: 500,
                    json: { message: 'Artifact temporarily unavailable' },
                });
            else
                await route.fulfill({
                    json: {
                        content: `Transcript revision ${artifactCalls}`,
                        format: 'text',
                    },
                });
        } else {
            detailCalls++;
            await route.fulfill({ json: job });
        }
    });
    await page.goto('/');
    await page.getByRole('button', { name: /Example recording/ }).click();
    await expect(page.locator('pre')).toContainText('revision 1');
    await expect.poll(() => detailCalls).toBe(1);
    await page.clock.fastForward(6000);
    await expect.poll(() => detailCalls).toBe(2);
    expect(artifactCalls).toBe(1);
    job = { ...job, stage: 'transcribe' };
    await page.clock.fastForward(6000);
    await expect(page.locator('pre')).toContainText('revision 2');
    expect(artifactCalls).toBe(2);
    await page.getByRole('button', { name: 'Refresh', exact: true }).click();
    await expect(page.locator('pre')).toContainText('revision 3');
    expect(artifactCalls).toBe(3);
    failArtifact = true;
    await page.getByRole('button', { name: 'Refresh', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText(
        'Artifact temporarily unavailable',
    );
    await expect(page.locator('pre')).toContainText('revision 3');
    await expect(page.getByText('Loading artifact…')).toHaveCount(0);
    expect(artifactCalls).toBe(4);
    failArtifact = false;
    await page.getByRole('button', { name: 'Retry', exact: true }).click();
    await expect(page.locator('pre')).toContainText('revision 5');
});

test('late artifact response cannot overwrite a newer job', async ({
    page,
}) => {
    const first = { ...ready, id: 'first', title: 'First selection' };
    const second = { ...ready, id: 'second', title: 'Second selection' };
    let release: (() => void) | undefined;
    await page.route('**/api/v1/**', async (route) => {
        const path = new URL(route.request().url()).pathname;
        if (path.endsWith('/jobs'))
            await route.fulfill({
                json: {
                    jobs: [first, second],
                    queues: ['main'],
                    invalid_records: 0,
                },
            });
        else if (path.endsWith('/first/transcript')) {
            await new Promise<void>((resolve) => {
                release = resolve;
            });
            await route.fulfill({
                json: { content: 'Old selection artifact', format: 'text' },
            });
        } else if (path.endsWith('/second/transcript'))
            await route.fulfill({
                json: { content: 'Current selection artifact', format: 'text' },
            });
        else
            await route.fulfill({
                json: path.endsWith('/first') ? first : second,
            });
    });
    await page.goto('/');
    await page.getByRole('button', { name: /First selection/ }).click();
    await expect.poll(() => Boolean(release)).toBe(true);
    await page.getByRole('button', { name: /Second selection/ }).click();
    await expect(page.locator('pre')).toContainText(
        'Current selection artifact',
    );
    const response = page.waitForResponse('**/first/transcript?queue=main');
    release?.();
    await response;
    await expect(page.locator('pre')).toContainText(
        'Current selection artifact',
    );
    await expect(page.locator('pre')).not.toContainText(
        'Old selection artifact',
    );
});
