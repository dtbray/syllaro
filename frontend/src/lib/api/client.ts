import type { components } from './schema';
export type Job = components['schemas']['JobView'];
export type JobList = components['schemas']['JobList'];
export type Artifact = components['schemas']['Artifact'];
export type Submission = components['schemas']['Submission'];
export async function request<T>(path: string, body?: unknown): Promise<T> {
    const response = await fetch(`/api/v1${path}`, {
        ...(body === undefined
            ? {}
            : {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify(body),
              }),
    });
    const data: unknown = await response.json();
    if (!response.ok) {
        const message = (data as components['schemas']['ErrorBody']).message;
        throw new Error(message || `Request failed (${response.status})`);
    }
    return data as T;
}
export function jobPath(job: Job): string {
    return `/jobs/${encodeURIComponent(job.id)}?queue=${encodeURIComponent(job.queue)}`;
}
export function artifactPath(job: Job, name: string): string {
    return `/jobs/${encodeURIComponent(job.id)}/${name}?queue=${encodeURIComponent(job.queue)}`;
}
