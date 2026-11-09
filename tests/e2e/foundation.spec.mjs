import { test, expect, fixture, login, api, apply } from './fixtures.mjs';
import { spawn } from 'node:child_process';
import { createServer } from 'node:net';
import { resolve } from 'node:path';
import { createHash, randomUUID } from 'node:crypto';

test('routed readers preserve originals, historical identities and directional Theme groups', async ({ page }, info) => {
  test.setTimeout(60000);
  await login(page, 'alice');
  const call = async (path, body) => {
    const response = await page.request.fetch(`/api/${path}`, { method: body ? 'POST' : 'GET', headers: { Origin: new URL(page.url()).origin }, ...(body ? { data: body } : {}) });
    expect(response.status(), await response.text()).toBe(200); return response.json();
  };
  const write = operations => call('apply', { contract_version: 'commons/0.1', idempotency_key: randomUUID(), operations });
  const ids = Object.fromEntries(['user', 'human', 'agent', 'task', 'source', 'theme', 'parent', 'child', 'document'].map(key => [key, randomUUID()]));
  const time = '2026-10-14T00:00:00Z';
  const object = (key, kind, title, fields) => ({ type: 'object', object: { id: ids[key], kind, title, description: `A concise synthetic ${kind} description.`, fields, revision: 7, created_by: null, updated_by: null, created_at: time, updated_at: time, archived_at: key === 'agent' ? time : null, protected: false, provenance: {}, authorship: {}, ...(kind === 'task' ? { owner_mapping: { source_owner_id: ids.user, destination_owner_id: ids.user } } : {}) } });
  const objects = [object('user', 'user', 'Synthetic imported system', { user_kind: 'system', avatar_asset_url: '/missing-synthetic-avatar.png', identities: [] }),
    object('human', 'user', 'Synthetic participant human', { user_kind: 'human', identities: [] }),
    object('agent', 'user', 'Synthetic participant agent', { user_kind: 'agent', identities: [] }),
    object('task', 'task', 'Synthetic imported assignment', { status: 'todo', priority: 'medium', owner_object_id: ids.user, due_at: null, work_kind: 'general', brief_markdown: 'Historical assignment, not a login account.' }),
    object('source', 'source', 'Synthetic source', { source_kind: 'document', byline: 'Synthetic author', original_language: 'en', original_media_type: 'text/plain' }),
    object('theme', 'theme', 'Synthetic theme', { slug: `theme-${ids.theme}` }), object('parent', 'theme', 'Synthetic parent', { slug: `parent-${ids.parent}` }), object('child', 'theme', 'Synthetic child', { slug: `child-${ids.child}` })];
  const body = '# Synthetic research document\n\n| Part | Count |\n| --- | --- |\n| Red | 3 |\n| Blue | 8 |\n\n- Exact α evidence\n- Second observation\n\n```text\n<not executable>\n```\n\n[Original](http://localhost:2999/objects/original)\n\n![Untrusted](https://example.test/never-load.png)\n\n' + 'Preserved supporting prose. '.repeat(4500) + '\n\nFinal evidence marker.';
  const artifacts = [{ type: 'artifact', id: ids.document, object_id: ids.source, created_by: null, created_at: time, provenance: {}, sha256: createHash('sha256').update(body).digest('hex'), artifact: { title: 'Research document with a clear readable title', kind: 'research_notes', body, media_type: 'text/markdown; charset=utf-8', metadata: { document_key: 'research' } } },
    ...Array.from({ length: 8 }, (_, index) => { const text = index === 1 ? '{"timing_seconds":42}' : `Original supporting file ${index}`; return { type: 'artifact', id: randomUUID(), object_id: ids.source, created_by: null, created_at: time, provenance: {}, sha256: createHash('sha256').update(text).digest('hex'), artifact: { body: text, media_type: 'text/plain', kind: 'transcript', metadata: { filename: index === 1 ? 'timing-1.json' : `captions-${index}${index === 0 ? '-unbrokenlongfilename'.repeat(12) : ''}.vtt` } } }; })];
  const connections = [['theme', 'parent', 'themed'], ['child', 'theme', 'themed'], ['source', 'theme', 'themed'], ['theme', 'user', 'involves'], ['theme', 'human', 'involves'], ['agent', 'theme', 'involves']].map(([from, to, kind]) => ({ type: 'connection', id: randomUUID(), from_id: ids[from], to_id: ids[to], kind, explanation: 'Original synthetic relationship', revision: 1, created_by: null, created_at: time, updated_at: time, archived_at: null, protected: false, provenance: {} }));
  await write([...objects, ...artifacts, ...connections].map(record => ({ op: 'import_record', source_store: 'synthetic-ui14-audit', record })));
  const source = (await call(`objects/${ids.source}`)).object;
  await write([{ op: 'update_object', object_id: source.id, expected_revision: source.revision, title: source.title, description: source.description, fields: { ...source.fields, current_artifact_id: ids.document } }]);
  const before = await call(`objects/${ids.source}`);
  await page.goto(`/sources/${ids.source}`);
  await expect(page.locator('.page-path')).toContainText('Synthetic source');
  await expect(page.getByText('Supporting attachments (8)', { exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: /captions-0/ })).not.toBeVisible();
  await page.screenshot({ path: info.outputPath('source-grouped-desktop.png') });
  await page.getByText('Supporting attachments (8)', { exact: true }).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('link', { name: /captions-0/ })).toBeVisible();
  await page.setViewportSize({ width: 1280, height: 500 });
  const supportingFile = page.getByRole('link', { name: /captions-7/ });
  await supportingFile.scrollIntoViewIfNeeded();
  const parentTop = await page.locator('.detail-page').evaluate(el => el.scrollTop);
  expect(parentTop).toBeGreaterThan(100);
  await supportingFile.click();
  await expect(page.getByRole('heading', { name: 'captions-7.vtt', exact: true })).toBeVisible();
  await page.goBack();
  await expect(supportingFile).toBeVisible();
  await expect.poll(() => page.locator('.detail-page').evaluate(el => el.scrollTop)).toBeCloseTo(parentTop, 0);
  await page.goForward();
  await page.getByRole('button', { name: 'Close reader', exact: true }).click();
  await expect(supportingFile).toBeVisible();
  await expect.poll(() => page.locator('.detail-page').evaluate(el => el.scrollTop)).toBeCloseTo(parentTop, 0);
  await supportingFile.click();
  await page.locator('.reader-parent').click();
  await expect(supportingFile).toBeVisible();
  await expect.poll(() => page.locator('.detail-page').evaluate(el => el.scrollTop)).toBeCloseTo(parentTop, 0);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('link', { name: /captions-0/ }).scrollIntoViewIfNeeded();
  await expect(page.getByRole('link', { name: /timing-1.json/ })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await page.screenshot({ path: info.outputPath('long-supporting-filename-narrow.png') });
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.getByRole('link', { name: /Research document with a clear readable title/ }).focus();
  await page.keyboard.press('Enter');
  const readerUrl = `/sources/${ids.source}/artifacts/${ids.document}`;
  await expect(page).toHaveURL(new RegExp(`${readerUrl}$`));
  await expect(page.getByRole('cell', { name: '8', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Synthetic research document' })).toBeVisible();
  await expect(page.locator('.artifact-markdown img')).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'Original (original local link)' })).toHaveAttribute('href', 'http://localhost:2999/objects/original');
  expect(await page.locator('.artifact-markdown').evaluate(el => getComputedStyle(el).overflowY)).toBe('visible');
  await page.screenshot({ path: info.outputPath('reader-markdown-desktop.png') });
  await page.goBack();
  await expect(page.getByRole('heading', { name: 'Synthetic source', exact: true })).toBeVisible();
  await page.goForward();
  await expect(page.getByRole('cell', { name: '3', exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('cell', { name: '8', exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath('reader-markdown-narrow.png') });
  const download = await page.getByRole('link', { name: 'Download original', exact: true }).getAttribute('href');
  expect(await (await page.request.get(download)).text()).toBe(body);
  expect(await call(`objects/${ids.source}`)).toEqual(before);
  await page.goto(`/users/${ids.user}`);
  await expect(page.getByText('External identities', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Historical provider profiles', exact: true })).toHaveCount(0);
  await page.goto(`/tasks/${ids.task}`);
  await expect(page.getByLabel('Assigned to Synthetic imported system', { exact: true })).toBeVisible();
  await expect(page.getByRole('img', { name: 'Synthetic imported system, System, owner', exact: true })).toBeVisible();
  await expect(page.getByLabel('Assigned to', { exact: true })).toHaveValue(ids.user);
  expect((await call('users')).users.some(user => user.id === ids.user)).toBe(false);
  await page.screenshot({ path: info.outputPath('imported-owner-narrow.png') });
  await page.setViewportSize({ width: 1280, height: 900 });
  for (const path of ['/tasks', '/tasks?view=kanban']) {
    await page.goto(path);
    await expect(page.getByRole('img', { name: 'Synthetic imported system, System, owner', exact: true })).toBeVisible();
  }
  await page.goto(`/themes/${ids.theme}`);
  for (const title of ['Parent Themes (1)', 'Child Themes (1)', 'Themed Objects (1)', 'Participants (3)']) await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Synthetic participant agent', exact: true })).toBeVisible();
  await expect(page.getByText('Archived identity', { exact: true })).toBeVisible();
  expect((await call(`objects/${ids.agent}`)).object.archived_at).not.toBeNull();
  await page.screenshot({ path: info.outputPath('theme-groups-desktop.png') });
  const participantGroup = page.locator('.detail-section').filter({ has: page.getByRole('heading', { name: 'Participants (3)', exact: true }) });
  await participantGroup.screenshot({ path: info.outputPath('theme-participants-detail.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => Promise.all(document.getAnimations().map(animation => animation.finished)));
  await page.getByText('Archived identity', { exact: true }).scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await participantGroup.screenshot({ path: info.outputPath('theme-participants-detail-narrow.png') });
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.getByRole('link', { name: 'Synthetic parent', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Child Themes (1)', exact: true })).toBeVisible();
  await page.goto(`/sources/${ids.source}`);
  await page.getByRole('button', { name: 'Sources', exact: true }).first().click();
  await expect(page.getByRole('link', { name: 'Open Synthetic source', exact: true })).toBeVisible();
  // Exercise real API pagination at a smaller page size, without mocking responses.
  await page.route('**/api/participants?*', async route => {
    const url = new URL(route.request().url()); url.searchParams.set('limit', '1');
    await route.continue({ url: url.toString() });
  });
  await page.route('**/api/objects?*', async route => {
    if (new URL(route.request().url()).searchParams.get('kind') === 'theme') await new Promise(resolve => setTimeout(resolve, 600));
    await route.continue();
  });
  await page.getByRole('navigation').getByRole('button', { name: 'Themes', exact: true }).click();
  await expect(page.getByRole('link', { name: 'Open Synthetic source', exact: true })).toHaveCount(0);
  await expect(page.getByRole('status')).toContainText('Loading themes');
  await expect(page.getByRole('link', { name: 'Open Synthetic theme', exact: true })).toBeVisible();
  for (const name of ['Synthetic imported system, System, participant', 'Synthetic participant human, Human, participant', 'Synthetic participant agent, Agent, participant']) await expect(page.getByRole('img', { name, exact: true })).toBeVisible();
  expect((await call('users')).users.some(user => [ids.user, ids.human, ids.agent].includes(user.id))).toBe(false);
  await page.screenshot({ path: info.outputPath('theme-participants-desktop.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath('theme-participants-narrow.png') });
});

test('Memory UI saves, searches, revises, escapes evidence and traverses a real link', async ({ page, request }, info) => {
  await login(page);
  await page.getByRole('button', { name: 'Memories', exact: true }).click();
  await page.getByRole('button', { name: 'New memory', exact: true }).click();
  await page.getByLabel('Title', { exact: true }).fill('Synthetic heliotrope customer protocol');
  await page.getByLabel('Description', { exact: true }).fill('Contact the synthetic customer after 14:00 Brisbane time.');
  await page.getByRole('button', { name: 'Create memory', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Synthetic heliotrope customer protocol', exact: true })).toBeVisible();
  const found = await api(request, 'objects?q=heliotrope');
  expect(found.objects).toHaveLength(1);
  const id = found.objects[0].id;
  expect(found.objects[0].created_by).toBe(fixture.bob_id);

  await page.getByRole('button', { name: 'Edit Object description', exact: true }).click();
  await page.getByRole('textbox', { name: 'Object description', exact: true }).fill('Contact after 15:30 Brisbane time, revised from supplied evidence.');
  await page.getByRole('textbox', { name: 'Object description', exact: true }).press('Control+Enter');
  await expect.poll(async () => (await api(request, `objects/${id}`)).object.description).toBe('Contact after 15:30 Brisbane time, revised from supplied evidence.');
  const body = '<img src=x onerror="window.fixtureExecuted=true"> synthetic bodyonlyzinnia evidence';
  await page.getByText('Add document or image', { exact: true }).click();
  await page.getByText('Append evidence', { exact: true }).click();
  await page.getByLabel('Append evidence (caller-supplied)').fill(body);
  await page.getByRole('button', { name: 'Append artifact', exact: true }).click();
  await page.getByRole('link', { name: /Caller-supplied evidence/ }).click();
  await expect(page.locator('.artifact-reader > pre')).toHaveText(body);
  expect(await page.evaluate(() => window.fixtureExecuted)).toBeUndefined();
  expect((await api(request, 'objects?q=bodyonlyzinnia')).objects).toEqual([]);

  // The foundation has no relationship creation UI. Use the actual scoped API,
  // then exercise its rendered explanation and navigation, not a mocked response.
  const note = await apply(request, [{ op: 'create_object', local_ref: 'note', kind: 'note',
    title: 'Synthetic customer call evidence', description: 'Caller-supplied fixture, not verified by Commons.', fields: {} }]);
  await apply(request, [{ op: 'create_connection', from_id: id, to_id: note.local_refs.note,
    from_revision: 3, to_revision: 1, kind: 'derived_from', explanation: 'Synthetic call supports the customer protocol.' }]);
  await page.getByRole('button', { name: 'Memories', exact: true }).first().click();
  await page.getByLabel('Search memories', { exact: true }).fill('heliotrope');
  await page.getByRole('link', { name: 'Open Synthetic heliotrope customer protocol', exact: true }).click();
  await expect(page.getByText('Synthetic call supports the customer protocol.', { exact: false })).toBeVisible();
  await expect(page.locator(`[title="${fixture.bob_id}"]`).first()).toBeVisible();
  const detail = await api(request, `objects/${id}`);
  expect(detail.object.revision).toBe(4);
  expect(detail.artifacts[0].origin).toBe('caller_supplied');
  expect(detail.audit_events).toHaveLength(4);
  await page.screenshot({ path: info.outputPath('memory-evidence.png'), fullPage: true });
  await page.getByRole('link', { name: 'Synthetic customer call evidence', exact: true }).first().click();
  await expect(page.getByRole('heading', { name: 'Synthetic customer call evidence', exact: true })).toBeVisible();
});

test('documents append versions, preserve stale drafts and expose history and incomplete captures', async ({ page, request }, info) => {
  const result = await apply(request, [{ op: 'create_object', local_ref: 'record', kind: 'memory', title: 'Synthetic research dossier', description: 'Document reader fixture.', fields: {} }]);
  const id = result.local_refs.record;
  await login(page);
  await page.goto(`/objects/${id}`);
  await expect(page.getByLabel('Upload research image')).not.toBeVisible();
  await page.getByText('Add document or image', { exact: true }).click();
  await page.getByRole('button', { name: 'New document', exact: true }).click();
  await page.getByLabel('Document title', { exact: true }).fill('Field guide');
  await page.getByLabel('Document content', { exact: true }).fill('# First edition\n\nExact **supplied** evidence.');
  await page.getByRole('button', { name: 'Save version', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Version saved' })).toBeVisible();
  await page.getByRole('link', { name: /Field guide Document/ }).click();
  await expect(page.getByRole('heading', { name: 'First edition', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Edit document', exact: true }).click();
  await page.getByLabel('Document content', { exact: true }).fill('# Second edition\n\nRevised evidence, originals retained.');
  await page.getByRole('button', { name: 'Save version', exact: true }).click();
  await expect.poll(async () => (await api(request, `objects/${id}`)).artifacts.length).toBe(2);
  await page.getByRole('link', { name: 'Read saved version', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Second edition', exact: true })).toBeVisible();
  await page.screenshot({ path: info.outputPath('document-current.png'), fullPage: true });
  await page.getByText(/^Document history \(/).click();
  await page.getByRole('link', { name: /Field guide.*historical version/ }).click();
  await expect(page.getByRole('heading', { name: 'First edition', exact: true })).toBeVisible();
  await page.screenshot({ path: info.outputPath('document-history.png'), fullPage: true });
  await page.getByRole('button', { name: 'Close reader', exact: true }).click();
  await page.getByRole('link', { name: /Field guide Document/ }).click();
  await page.getByRole('button', { name: 'Edit document', exact: true }).click();
  await page.getByLabel('Document content', { exact: true }).fill('My unsaved third edition');
  const draftUrl = page.url();
  page.once('dialog', dialog => dialog.dismiss());
  await page.goBack();
  await expect(page).toHaveURL(draftUrl);
  await expect(page.getByLabel('Document content', { exact: true })).toHaveValue('My unsaved third edition');
  const detail = await api(request, `objects/${id}`);
  await apply(request, [{ op: 'append_artifact', object_id: id, expected_revision: detail.object.revision, body: 'Concurrent supplied evidence' }]);
  await page.getByRole('button', { name: 'Save version', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('draft is preserved');
  await expect(page.getByLabel('Document content', { exact: true })).toHaveValue('My unsaved third edition');
  await page.screenshot({ path: info.outputPath('document-conflict.png'), fullPage: true });
  await page.getByRole('button', { name: 'Cancel document edit', exact: true }).click();
  await apply(request, [{ op: 'save_artifact', object_id: id, expected_revision: detail.object.revision + 1, artifact: { title: 'Incomplete capture', body: 'Opening only', capture_outcome: 'incomplete', capture_reason: 'Remaining pages unavailable' } }]);
  await page.getByRole('button', { name: 'Close reader', exact: true }).click();
  await page.getByText(/^Supporting attachments \(/).click();
  await page.getByRole('link', { name: /Incomplete capture/ }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Capture limitation:' })).toContainText('Remaining pages unavailable');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: info.outputPath('document-incomplete-narrow.png'), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);

  // Real imported unknown media must remain unknown through the document editor.
  const origin = new URL(page.url()).origin;
  const admin = await request.post('/api/login', { data: { username: 'alice', password: fixture.password },
    headers: { Origin: origin } });
  expect(admin.status()).toBe(200);
  const original = 'Exact historical α\r\n<not-markdown> evidence';
  const aid = randomUUID();
  const imported = await request.post('/api/apply', { headers: { Origin: origin }, data: {
    contract_version: 'commons/0.1', idempotency_key: randomUUID(), operations: [{ op: 'import_record', source_store: 'synthetic-ui', record: {
      type: 'artifact', id: aid, object_id: id, created_by: null, created_at: '2020-01-01T00:00:00Z', provenance: {},
      sha256: createHash('sha256').update(original).digest('hex'), artifact: { kind: 'research_notes', title: 'Unknown-media original',
        body: original, media_type: null, metadata: { document_key: aid } },
    } }],
  } });
  expect(imported.status()).toBe(200);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.getByRole('button', { name: 'Close reader', exact: true }).click();
  await page.getByRole('link', { name: /Unknown-media original Document/ }).click();
  expect(await page.locator('.artifact-reader > pre').textContent()).toBe(original);
  await page.screenshot({ path: info.outputPath('document-unknown-original.png'), fullPage: true });
  await page.getByRole('button', { name: 'Edit document', exact: true }).click();
  await page.getByLabel('Document content', { exact: true }).fill('Later edit; original remains in history.');
  await page.getByRole('button', { name: 'Save version', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Version saved' })).toBeVisible();
  const versions = (await api(request, `objects/${id}`)).artifacts.filter(a => a.id === aid || a.supersedes_artifact_id === aid);
  expect(versions).toHaveLength(2);
  expect(versions.every(a => a.media_type === null)).toBe(true);
  expect(versions.find(a => a.id === aid).body).toBe(original);
  await page.getByRole('link', { name: 'Read saved version', exact: true }).click();
  await expect(page.locator('.artifact-reader > pre')).toHaveText('Later edit; original remains in history.');
  await page.getByText(/^Document history \(/).click();
  await page.getByRole('link', { name: /Unknown-media original.*historical version/ }).click();
  expect(await page.locator('.artifact-reader > pre').textContent()).toBe(original);
  await page.screenshot({ path: info.outputPath('document-unknown-history.png'), fullPage: true });
  await page.getByRole('button', { name: 'Close reader', exact: true }).click();
  await expect(page.locator('.artifact-reader')).toHaveCount(0);
  await page.getByText('Add document or image', { exact: true }).click();
  // The two-pixel red/blue PNG used by the HTTP image acceptance test, with valid CRCs.
  const pixels = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAIAAAABCAIAAAB7QOjdAAAADUlEQVR4nGP4zwAE/wEHAAH/4iOeWQAAAABJRU5ErkJggg==', 'base64');
  await page.getByLabel('Upload research image').setInputFiles({ name: 'Synthetic pixels.png', mimeType: 'image/png', buffer: pixels });
  // Returning from the reader preserved the open supporting-file disclosure.
  await page.getByRole('link', { name: /Synthetic pixels.png Image/ }).click();
  const image = page.getByRole('img', { name: 'Synthetic pixels.png', exact: true });
  await expect.poll(() => image.evaluate(img => img.complete && img.naturalWidth)).toBe(2);
  const download = await page.getByRole('link', { name: 'Download original', exact: true }).getAttribute('href');
  expect(await (await page.request.get(download)).body()).toEqual(pixels);
});

test('research records retain precise dates, categories and exact evidence through the UI', async ({ page }, info) => {
  test.setTimeout(60000);
  await login(page);
  const session = async (path, data) => {
    const response = await page.request.fetch(`/api/${path}`, { method: data ? 'POST' : 'GET', headers: { Origin: new URL(page.url()).origin }, ...(data ? { data } : {}) });
    expect(response.status()).toBe(200); return response.json();
  };
  const write = operations => session('apply', { contract_version: 'commons/0.1', idempotency_key: crypto.randomUUID(), operations });
  await page.getByRole('button', { name: 'Sources', exact: true }).click();
  await page.getByRole('button', { name: 'New source', exact: true }).click();
  await page.getByLabel('Title', { exact: true }).fill('Synthetic marsh research');
  await page.getByLabel('Source kind', { exact: true }).selectOption('paper');
  await page.getByLabel('Byline', { exact: true }).fill('Synthetic author');
  const canonical = 'https://example.test/research/' + 'long-reference-'.repeat(12);
  await page.getByLabel('Canonical uri', { exact: true }).fill(canonical);
  await page.getByRole('button', { name: 'Create source', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Synthetic marsh research', exact: true })).toBeVisible();
  const id = page.url().split('/').pop();
  const saved = await write([{ op: 'save_artifact', object_id: id, expected_revision: 1, artifact: { body: 'αβ quoted words and ending', title: 'Original capture', kind: 'paper_text' } }]);
  const aid = saved.changes[0].artifact_id;
  await page.reload();
  const properties = page.getByRole('region', { name: 'Source properties', exact: true });
  await expect(properties.getByRole('link', { name: canonical, exact: true })).toHaveAttribute('href', canonical);
  await expect(page.getByRole('heading', { name: 'Research details', exact: true })).toHaveCount(0);
  await expect(page.getByText('Synthetic author', { exact: true })).toHaveCount(1);
  await expect(page.getByRole('link', { name: /Original capture/ })).toBeInViewport();
  await expect(page.getByLabel('Upload research image')).not.toBeVisible();
  // Ordinary scalars must not inherit the transcript's bordered monospace box.
  expect(await properties.getByText('Synthetic author', { exact: true }).evaluate(el =>
    [getComputedStyle(el).borderTopWidth, getComputedStyle(el).paddingTop])).toEqual(['0px', '0px']);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath('source-long-url-narrow.png'), fullPage: true });
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.getByRole('button', { name: 'Edit research details' }).click();
  await page.getByLabel('Publisher', { exact: true }).fill('Synthetic Press');
  await page.getByLabel('Current artifact', { exact: true }).selectOption(aid);
  await page.getByRole('button', { name: 'Save research details' }).click();
  await expect.poll(async () => (await session(`objects/${id}`)).object.fields.current_artifact_id).toBe(aid);
  const evidence = page.getByRole('link', { name: 'Read current capture', exact: true });
  await expect(evidence).toHaveAttribute('href', `/objects/${id}/artifacts/${aid}`);
  expect(await (await page.request.get(`/api/artifacts/${aid}/content`)).text()).toBe('αβ quoted words and ending');
  await page.screenshot({ path: info.outputPath('source-details.png'), fullPage: true });
  // A stale structured edit preserves both the local draft and the external winner.
  await page.getByRole('button', { name: 'Edit research details' }).click();
  await page.getByLabel('Byline', { exact: true }).fill('Unsaved local author');
  const old = (await session(`objects/${id}`)).object;
  await write([{ op: 'update_object', object_id: id, expected_revision: old.revision,
    title: old.title, description: old.description, fields: { ...old.fields, publisher: 'Concurrent publisher' } }]);
  await page.getByRole('button', { name: 'Save research details' }).click();
  await expect(page.getByRole('alert')).toContainText('revision conflict');
  await expect(page.getByLabel('Byline', { exact: true })).toHaveValue('Unsaved local author');
  await page.getByRole('button', { name: 'Cancel details', exact: true }).click();
  await page.getByRole('button', { name: 'Refresh current view', exact: true }).click();
  await expect(properties.getByText('Concurrent publisher', { exact: true })).toBeVisible();
  expect((await session(`objects/${id}`)).object.fields.byline).toBe('Synthetic author');
  const history = page.getByText(/^Revision history \(/);
  await history.focus();
  await page.keyboard.press('Enter');
  await page.locator('summary').filter({ hasText: /^Revision \d+ ·/ }).first().click();
  await expect(page.getByRole('heading', { name: 'Before', exact: true })).toBeVisible();
  await history.click();
  const longText = 'Synthetic original Unicode λ evidence.\n'.repeat(35000) + 'Exact final line.';
  const current = (await session(`objects/${id}`)).object.revision;
  await write([{ op: 'save_artifact', object_id: id, expected_revision: current, artifact: { title: 'Long original capture', body: longText, semantic_indexing_enabled: false } }]);
  await page.reload();
  await page.getByText(/^Supporting attachments \(/).click();
  await page.getByRole('link', { name: /Long original capture/ }).click();
  expect(await page.locator('.artifact-reader > pre').textContent()).toBe(longText);
  await page.getByRole('button', { name: 'Notes', exact: true }).first().click();
  await page.getByRole('button', { name: 'New note', exact: true }).click();
  await page.getByLabel('Title', { exact: true }).fill('Synthetic exact quotation');
  await page.getByLabel('Content', { exact: true }).fill('quoted words');
  await page.getByRole('button', { name: 'Create note', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Synthetic exact quotation' })).toBeVisible();
  const note = page.url().split('/').pop();
  await page.getByRole('button', { name: 'Edit research details' }).click();
  await page.getByLabel('Intent', { exact: true }).selectOption('excerpt');
  await page.getByLabel('Source artifact id', { exact: true }).fill(aid);
  await page.getByLabel('Locator kind', { exact: true }).selectOption('text_offset');
  await page.getByLabel('Start', { exact: true }).fill('3');
  await page.getByLabel('End', { exact: true }).fill('15');
  await page.getByRole('button', { name: 'Save research details' }).click();
  await expect.poll(async () => (await session(`objects/${note}`)).object.fields.source_locator).toEqual({ kind: 'text_offset', start: 3, end: 15 });
  await expect(page.getByRole('button', { name: 'Edit Note content', exact: true })).toBeVisible();
  await expect(page.getByText('quoted words', { exact: true })).toHaveCount(1);
  const excerpt = page.getByRole('link', { name: /Read original excerpt evidence/ });
  await expect(excerpt).toHaveAttribute('href', `/objects/${id}/artifacts/${aid}?excerpt=${note}`);
  await excerpt.click();
  await expect(page.locator('mark')).toHaveText('quoted words');
  await expect(page.locator('.artifact-reader .stored-text')).toHaveText('αβ quoted words and ending');
  await page.reload();
  await expect(page.locator('mark')).toHaveText('quoted words');
  await page.getByRole('button', { name: 'Events', exact: true }).first().click();
  await page.getByRole('button', { name: 'New event', exact: true }).click();
  await page.getByLabel('Title', { exact: true }).fill('Synthetic year-only event');
  await page.getByLabel('Starts at', { exact: true }).fill('2021');
  await page.getByLabel('Starts at precision', { exact: true }).selectOption('year');
  await page.getByRole('button', { name: 'Create event', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Synthetic year-only event' })).toBeVisible();
  const event = page.url().split('/').pop();
  expect((await session(`objects/${event}`)).object.fields).toEqual({ starts_at: '2021', starts_at_precision: 'year' });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: info.outputPath('event-narrow.png'), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.getByRole('button', { name: 'Themes', exact: true }).first().click();
  await page.getByRole('button', { name: 'New theme', exact: true }).click();
  await page.getByLabel('Title', { exact: true }).fill('Synthetic fieldwork theme');
  await page.getByLabel('Slug', { exact: true }).fill('synthetic-fieldwork');
  await page.getByRole('button', { name: 'Create theme', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Synthetic fieldwork theme' })).toBeVisible();
  expect((await session(`objects/${page.url().split('/').pop()}`)).object.fields.slug).toBe('synthetic-fieldwork');
  await page.getByRole('button', { name: 'Entities', exact: true }).first().click();
  await page.getByRole('button', { name: 'New entity', exact: true }).click();
  await page.getByLabel('Title', { exact: true }).fill('Synthetic research institute');
  await page.getByLabel('Kind', { exact: true }).fill('organization');
  await page.getByRole('button', { name: 'Create entity', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Synthetic research institute' })).toBeVisible();
  for (const slug of ['research-institute', 'field-station']) {
    await page.getByText('Define an Entity category', { exact: true }).click();
    await page.getByLabel('Category slug', { exact: true }).fill(slug);
    await page.getByLabel('Category label', { exact: true }).fill(slug);
    await page.getByLabel('Category definition', { exact: true }).fill('Synthetic classification definition');
    await page.getByLabel('Category aliases', { exact: true }).fill(slug + '-alias');
    await page.getByLabel('Category legacy kind', { exact: true }).selectOption('organization');
    await page.getByRole('button', { name: 'Create category', exact: true }).click();
    await expect.poll(async () => (await session('entity-categories')).categories.some(c => c.slug === slug)).toBe(true);
    await page.getByText('Define an Entity category', { exact: true }).click();
  }
  await page.getByRole('button', { name: 'Edit research details' }).click();
  await page.getByRole('checkbox', { name: 'research-institute', exact: true }).check();
  await page.getByRole('checkbox', { name: 'field-station', exact: true }).check();
  await page.getByRole('button', { name: 'Save research details' }).click();
  await expect(page.getByRole('button', { name: 'Edit research details' })).toBeVisible();
  const entity = page.url().split('/').pop();
  expect((await session(`objects/${entity}`)).object.fields.category_ids).toHaveLength(2);
  await expect(page.getByText('research-institute · Primary category', { exact: true })).toBeVisible();
  await expect(page.getByText('field-station', { exact: true })).toBeVisible();
  await page.getByText('Preservation tools', { exact: true }).click();
  await page.getByRole('button', { name: 'Protect record', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Remove protection', exact: true })).toBeVisible();
  await page.getByText('Correct evidence', { exact: true }).click();
  await page.getByLabel('Correction reason', { exact: true }).fill('Synthetic corrected classification');
  await page.getByLabel('Corrected representation', { exact: true }).fill('Current evidence assertion, original retained.');
  await page.getByRole('button', { name: 'Save correction', exact: true }).click();
  await expect(page.getByText('Current evidence assertion, original retained.', { exact: true })).toBeVisible();
  await page.screenshot({ path: info.outputPath('entity-correction.png'), fullPage: true });
  await page.getByRole('button', { name: 'Archive record', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Restore record', exact: true })).toBeVisible();
  expect((await session('objects?kind=entity')).objects.some(o => o.id === entity)).toBe(false);
  await page.screenshot({ path: info.outputPath('archived-record.png'), fullPage: true });
  // Archiving preserves direct reads, but ordinary collections have one current view.
  expect((await session('objects?kind=entity&archived=true')).objects.some(o => o.id === entity)).toBe(true);
  await page.getByRole('button', { name: 'Objects', exact: true }).first().click();
  await expect(page.locator('.list-group-head strong')).toHaveText('Objects');
  await expect(page.getByRole('button', { name: /^(Active|Archived) records$/ })).toHaveCount(0);
  await expect(page.getByText('Synthetic research institute', { exact: true })).toHaveCount(0);
  await expect(page.getByText('Synthetic fieldwork theme', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Refresh current view' }).click();
  await expect(page.getByRole('button', { name: 'Refresh current view' })).toBeEnabled();
  await page.reload();
  await expect(page.getByText('Synthetic fieldwork theme', { exact: true })).toBeVisible();
  await expect(page.getByText('Synthetic research institute', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Entities', exact: true }).first().click();
  await expect(page.getByLabel('Search entities')).toBeVisible();
  await expect(page.getByText('Synthetic research institute', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /^(Active|Archived) records$/ })).toHaveCount(0);
  await page.goto(`/objects/${entity}`);
  await expect(page.getByRole('heading', { name: 'Synthetic research institute' })).toBeVisible();
  expect((await session(`objects/${entity}`)).object.archived_at).not.toBeNull();

});

for (const workKind of ['general', 'code']) {
  test(`Task UI permits an unlinked ${workKind} Task and preserves required date/local-time meaning`, async ({ page, request }, info) => {
    const issueUrl = `https://github.com/synthetic/commons/issues/${workKind === 'general' ? 27 : 28}`;
    await login(page);
    await page.getByRole('button', { name: 'Tasks', exact: true }).click();
    await page.getByRole('button', { name: 'New task', exact: true }).click();
    await page.getByLabel('Title', { exact: true }).fill(`Synthetic ${workKind} onboarding Task`);
    await page.getByRole('combobox', { name: 'Work kind', exact: true }).selectOption(workKind);
    const due = page.getByLabel('Due date & time (required; local time)', { exact: true });
    const issue = page.getByLabel('GitHub Issue (optional)', { exact: true });
    expect(await due.evaluate(el => el.validity.valueMissing)).toBe(true);
    expect(await issue.evaluate(el => el.validity.valueMissing)).toBe(false);
    await page.getByRole('button', { name: 'Create task', exact: true }).click();
    await expect(page.getByRole('dialog', { name: 'New task', exact: true })).toBeVisible();
    expect((await api(request, `objects?q=Synthetic%20${workKind}%20onboarding%20Task`)).objects).toHaveLength(0);
    await due.fill('2027-04-03T14:25');
    await issue.fill('https://github.com/synthetic/commons/issues/01');
    expect(await issue.evaluate(el => el.validity.patternMismatch)).toBe(true);
    await page.getByRole('button', { name: 'Create task', exact: true }).click();
    await expect(page.getByRole('dialog', { name: 'New task', exact: true })).toBeVisible();
    await issue.fill('');
    await page.getByRole('combobox', { name: 'Priority', exact: true }).selectOption('high');
    await page.getByLabel('Brief (required before doing)', { exact: true }).fill('Confirm the synthetic customer protocol.');
    await page.getByRole('button', { name: 'Create task', exact: true }).click();
    await expect(page.getByRole('heading', { name: `Synthetic ${workKind} onboarding Task`, exact: true })).toBeVisible();
    const result = await api(request, `objects?q=Synthetic%20${workKind}%20onboarding%20Task`);
    expect(result.objects).toHaveLength(1);
    expect(result.objects[0].fields).toMatchObject({ due_at: '2027-04-03T04:25:00.000Z',
      priority: 'high', owner_object_id: fixture.bob_id });
    expect(result.objects[0].fields.github_issue_url).toBeUndefined();
    await expect(page.getByLabel('Due (required; local time)', { exact: true })).toHaveValue('2027-04-03T14:25');
    await page.getByText('More details', { exact: true }).click();
    await expect(page.getByRole('button', { name: 'Edit GitHub issue URL', exact: true })).toContainText('Not linked');
    await page.screenshot({ path: info.outputPath('task-unlinked.png'), fullPage: true });
    await page.getByRole('button', { name: 'Edit GitHub issue URL', exact: true }).click();
    await page.getByLabel('GitHub issue URL', { exact: true }).fill(issueUrl);
    await page.getByRole('button', { name: 'Save GitHub issue URL', exact: true }).click();
    await expect(page.getByRole('link', { name: /Open GitHub issue/ })).toBeVisible();
    expect((await api(request, `objects/${result.objects[0].id}`)).object.fields.github_issue_url).toBe(issueUrl);
    await page.screenshot({ path: info.outputPath('task-linked-issue.png'), fullPage: true });
    await page.getByLabel('Priority', { exact: true }).selectOption('low');
    await expect.poll(async () => (await api(request, `objects/${result.objects[0].id}`)).object.fields.priority).toBe('low');
    await page.getByLabel('Task status', { exact: true }).selectOption('doing');
    await expect.poll(async () => (await api(request, `objects/${result.objects[0].id}`)).object.fields.status).toBe('doing');
    const saved = (await api(request, `objects/${result.objects[0].id}`)).object;
    expect(saved.fields).toMatchObject({ due_at: '2027-04-03T04:25:00.000Z',
      github_issue_url: issueUrl, work_kind: workKind,
      brief_markdown: 'Confirm the synthetic customer protocol.', priority: 'low', owner_object_id: fixture.bob_id });
    expect(saved.revision).toBe(4);
  });
}

test('stale browser draft survives conflict and Reload latest reads the external winner', async ({ page, request }, info) => {
  const created = await apply(request, [{ op: 'create_object', local_ref: 'memory', kind: 'memory',
    title: 'Synthetic cassowary decision', description: 'Initial evidence.', fields: {} }]);
  const id = created.local_refs.memory;
  await login(page);
  await page.getByRole('link', { name: 'Open Synthetic cassowary decision', exact: true }).click();
  await page.getByRole('button', { name: 'Edit Object description', exact: true }).click();
  await apply(request, [{ op: 'update_object', object_id: id, expected_revision: 1,
    title: 'Synthetic cassowary decision', description: 'New evidence from the external writer.', fields: {} }]);
  await page.getByRole('textbox', { name: 'Object description', exact: true }).fill('Unsaved browser draft, preserve me.');
  await page.getByRole('button', { name: 'Save Object description', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Server data changed.' })).toBeVisible();
  await expect(page.getByRole('textbox', { name: 'Object description', exact: true })).toHaveValue('Unsaved browser draft, preserve me.');
  await page.getByRole('button', { name: 'Refresh current view', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Unsaved draft preserved');
  await expect(page.getByRole('textbox', { name: 'Object description', exact: true })).toHaveValue('Unsaved browser draft, preserve me.');
  await page.screenshot({ path: info.outputPath('revision-conflict.png'), fullPage: true });
  await page.getByRole('button', { name: 'Reload server value', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Synthetic cassowary decision', exact: true })).toBeVisible();
  await expect(page.getByText('New evidence from the external writer.', { exact: true }).last()).toBeVisible();
  expect((await api(request, `objects/${id}`)).object.revision).toBe(2);
});

test('reader cannot edit, and browser-issued scoped credential is revoked for real', async ({ page, request }, info) => {
  await apply(request, [{ op: 'create_object', local_ref: 'memory', kind: 'memory',
    title: 'Synthetic gardenia reader fixture', description: 'A reader can inspect but not mutate this record.', fields: {} }]);
  await login(page, 'reader');
  await expect(page.getByRole('button', { name: 'New object', exact: true })).toHaveCount(0);
  await page.getByRole('link', { name: 'Open Synthetic gardenia reader fixture', exact: true }).click();
  await expect(page.getByRole('button', { name: /^Edit / })).toHaveCount(0);
  await expect(page.getByLabel('Append evidence (caller-supplied)')).toHaveCount(0);
  await page.screenshot({ path: info.outputPath('reader-memory.png'), fullPage: true });
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await login(page);
  await page.getByRole('button', { name: 'Access', exact: true }).click();
  await page.getByLabel('Label', { exact: true }).fill('Synthetic browser credential');
  await page.getByLabel('memory', { exact: true }).check();
  await page.getByRole('button', { name: 'Create credential', exact: true }).click();
  const token = await page.getByLabel('New agent token', { exact: true }).inputValue();
  expect(token.length).toBeGreaterThan(20);
  await api(request, 'me', undefined, token);
  await apply(request, [{ op: 'create_object', local_ref: 'denied', kind: 'task',
    title: 'Scope is checked before invalid fields', description: '', fields: {} }], token, 403);
  await page.getByRole('button', { name: 'Dismiss secret', exact: true }).click();
  await page.getByRole('button', { name: 'Revoke Synthetic browser credential', exact: true }).click();
  await expect(page.getByLabel('New agent token', { exact: true })).toHaveCount(0);
  await api(request, 'me', undefined, token, 401);
});

for (const [entry, name, theme] of [
  ['COMMONS_PROTECTED_DEMO_USER', 'Commons', 'charcoal'],
  ['COMMONS_LOCAL_USER', 'Beacon', 'blue-slate'],
  ['COMMONS_LOCAL_USER', 'Estuary', 'charcoal'],
]) {
test(`${entry} ${name} opens with installation branding, edits, and renews without a login form`, async ({ page, context, request }, info) => {
  const reservation = createServer();
  await new Promise(resolve => reservation.listen(0, '127.0.0.1', resolve));
  const port = reservation.address().port;
  await new Promise(resolve => reservation.close(resolve));
  const origin = `http://127.0.0.1:${port}`;
  const server = spawn('target/debug/commons', ['serve'], { cwd: resolve(import.meta.dirname, '../..'),
    env: { ...process.env, PORT: String(port), COMMONS_ORIGIN: origin, [entry]: fixture.bob_id,
      ...(name === 'Commons' ? {} : { COMMONS_INSTALLATION_NAME: name, COMMONS_THEME: theme }) },
    stdio: 'ignore' });
  try {
    await expect.poll(async () => {
      try { return (await request.get(`${origin}/api/health`)).status(); } catch { return 0; }
    }).toBe(200);
    expect((await (await request.get(`${origin}/api/health`)).json()).branding).toEqual({ name, theme });
    await page.goto(`${origin}/objects`);
    await expect(page.getByRole('navigation', { name, exact: true })).toBeVisible();
    await expect(page).toHaveTitle(`${name} — Context`);
    await expect(page.locator('.brand-name')).toHaveText(name);
    await expect(page.locator('.brand > .brand-mark')).toHaveText(name[0]);
    const backgrounds = await page.evaluate(() => ['.nav-rail', '.workspace'].map(selector => getComputedStyle(document.querySelector(selector)).backgroundColor));
    expect(backgrounds).toEqual(theme === 'blue-slate' ? ['rgb(17, 29, 41)', 'rgb(23, 35, 48)'] : ['rgb(9, 10, 11)', 'rgb(13, 14, 16)']);
    await expect(page.getByLabel('Username', { exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: /^Sign (in|out)$/ })).toHaveCount(0);
    await page.screenshot({ path: info.outputPath('direct-entry.png') });
    await page.getByRole('button', { name: 'Collapse navigation', exact: true }).click();
    await expect(page.locator('.collapsed-brand-mark')).toBeVisible();
    await expect(page.locator('.collapsed-brand-mark')).toHaveText(name[0]);
    await page.screenshot({ path: info.outputPath('branding-collapsed.png') });
    await page.getByRole('button', { name: 'Expand navigation', exact: true }).focus();
    await page.keyboard.press('Enter');
    await expect(page.locator('.brand-name')).toBeVisible();
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.locator('.collapsed-brand-mark')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: info.outputPath('branding-narrow.png') });
    await page.setViewportSize({ width: 1280, height: 900 });
    const title = `Synthetic ${entry} ${name} browser check`;
    const created = await apply(request, [{ op: 'create_object', local_ref: 'memory', kind: 'memory',
      title, description: 'Before UI edit.', fields: {} }]);
    const id = created.local_refs.memory;
    await page.goto(`${origin}/objects/${id}`);
    await page.getByRole('button', { name: 'Edit Object description', exact: true }).click();
    await page.getByRole('textbox', { name: 'Object description', exact: true }).fill('Persisted without a Commons sign-in.');
    await page.getByRole('textbox', { name: 'Object description', exact: true }).press('Control+Enter');
    await expect.poll(async () => (await api(request, `objects/${id}`)).object.description).toBe('Persisted without a Commons sign-in.');
    await context.clearCookies();
    await page.getByRole('button', { name: 'Memories', exact: true }).first().click();
    await expect(page.getByRole('link', { name: `Open ${title}`, exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: /^Sign (in|out)$/ })).toHaveCount(0);
    await expect(page).toHaveTitle(`${name} — Context`);
    await expect(page.locator('.brand-name')).toHaveText(name);
    expect((await api(request, `objects/${id}`)).object.revision).toBe(2);
  } finally {
    if (server.exitCode === null) {
      const stopped = new Promise(resolve => server.once('exit', resolve));
      server.kill('SIGTERM');
      await stopped;
    }
  }
});
}
