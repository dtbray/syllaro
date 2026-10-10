# UI components

Syllaro uses shadcn-svelte's Vega preset (CLI 1.7.0, retrieved 2026-10-09).
Component source is copied into `src/lib/components/ui`; it is maintained in this
repository rather than fetched at runtime. The upstream MIT license is retained
in `licenses/shadcn-svelte.txt`.

`components.json` records registry, theme, and aliases. Add components from the
frontend directory with `npx shadcn-svelte@1.7.0 add COMPONENT`, review generated
source and dependency changes, and pin added dependencies exactly. Commit the
npm lock. Avoid overwriting customized components without reviewing the diff.

Bits UI supplies accessible tab and scrollbar behavior. Tailwind variants and
`cn` compose styles. Icons, animation styles and the Inter variable font
are bundled locally; no external font or component service is required. Component
styling follows the system light/dark preference. Custom CSS is limited to
Markdown content and theme variables; queue/application logic stays in App.svelte.

Validate with `npm run check`, `npm run build`, and `npm test`. Browser tests use
mock jobs and cover submission, polling, retry, tab keyboard interaction, safe
Markdown rendering, and error recovery. Components don't change worker behavior.
