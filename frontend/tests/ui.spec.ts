import { test, expect } from '@playwright/test';
const initial = { id: 'example', queue: 'main', title: 'Example recording', source: 'https://youtu.be/example', kind: 'youtube', profile: 'local', status: 'failed', created: 1700000000, error: 'Download failed', artifacts: ['transcript', 'briefing'] };
test('select job, preserve transcript labels, sanitize briefing, and retry', async ({ page }) => {
  let job = { ...initial };
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown;
    if (path.endsWith('/transcript')) body = { content: '[00:12] SPEAKER_00: Review the plan.', format: 'text' };
    else if (path.endsWith('/briefing')) body = { content: '## Plan\n<script>window.infected=true</script>\n<img src=x onerror="window.infected=true">\n[bad](javascript:alert(1))', format: 'markdown' };
    else if (path.endsWith('/retry')) { job = { ...job, status: 'pending', error: '' }; body = job; }
    else if (path.endsWith('/jobs')) body = { jobs: [job], queues: ['main'], invalid_records: 0 };
    else body = job;
    await route.fulfill({ json: body });
  });
  await page.goto('/');
  await page.getByRole('button', { name: /Example recording/ }).click();
  await expect(page.getByText('Download failed', { exact: true })).toBeVisible();
  await page.getByText('Transcript', { exact: true }).click();
  await expect(page.locator('pre')).toContainText('[00:12] SPEAKER_00');
  await expect(page.locator('.markdown script')).toHaveCount(0);
  await expect(page.locator('.markdown [onerror]')).toHaveCount(0);
  await expect(page.locator('.markdown a[href^="javascript:"]')).toHaveCount(0);
  expect(await page.evaluate(() => (window as unknown as Record<string, unknown>).infected)).toBeUndefined();
  await page.getByRole('button', { name: 'Retry failed job' }).click();
  await expect(page.getByText('Retry queued using the existing lifecycle.')).toBeVisible();
});
test('submit source, show failure, and refresh without a full reload', async ({ page }) => {
  let jobs: unknown[] = [];
  await page.route('**/api/v1/**', async route => {
    if (route.request().method() === 'POST') {
      expect(route.request().postDataJSON().source).toBe('https://youtu.be/new');
      const job = { ...initial, id: 'new', status: 'pending', error: null, artifacts: [] };
      jobs = [job]; await route.fulfill({ status: 201, json: job });
    } else if (new URL(route.request().url()).pathname.endsWith('/jobs')) await route.fulfill({ json: { jobs, queues: ['main'], invalid_records: 0 } });
    else await route.fulfill({ json: jobs[0] });
  });
  await page.goto('/');
  await page.getByLabel('YouTube source').fill('https://example.com/not-youtube');
  await page.getByRole('button', { name: 'Add to queue' }).click();
  await expect(page.getByRole('alert')).toContainText('YouTube URL');
  await page.getByLabel('YouTube source').fill('https://youtu.be/new');
  await page.getByRole('button', { name: 'Add to queue' }).click();
  await expect(page.getByRole('status')).toContainText('Queued');
  jobs = [{ ...initial, id: 'new', title: 'Worker finished', status: 'transcribed', error: null, artifacts: [] }];
  await expect(page.getByRole('button', { name: /Worker finished/ })).toBeVisible({ timeout: 10000 });
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await expect(page.getByRole('button', { name: /Worker finished/ })).toBeVisible();
});
test('API failure is visible and manual refresh recovers', async ({ page }) => {
  let unavailable = true;
  await page.route('**/api/v1/jobs', async route => {
    if (unavailable) await route.fulfill({ status: 500, json: { code: 'storage_error', message: 'Queue storage is unavailable' } });
    else await route.fulfill({ json: { jobs: [], queues: ['main'], invalid_records: 0 } });
  });
  await page.goto('/');
  await expect(page.getByRole('alert')).toContainText('Queue storage is unavailable');
  unavailable = false;
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await expect(page.getByRole('alert')).toHaveCount(0);
});
