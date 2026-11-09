import { randomUUID } from 'node:crypto';
import { test, expect, fixture, login } from './fixtures.mjs';

test('conversation coverage, visible tools, Run history, reader access and confirmed deletion', async ({ page, browser }, info) => {
  await login(page);
  const call = async (route, body, expected = 200) => {
    const response = await page.request.fetch(`/api/${route}`, {
      method: body === undefined ? 'GET' : 'POST', headers: { Origin: new URL(page.url()).origin },
      ...(body === undefined ? {} : { data: body }),
    });
    expect(response.status()).toBe(expected);
    return response.json();
  };
  await page.getByRole('navigation').getByRole('button', { name: 'Threads', exact: true }).click();
  await expect(page.getByText('No threads saved.', { exact: true })).toBeVisible();
  await page.screenshot({ path: info.outputPath('conversations-empty.png'), fullPage: true });
  const linked = await call('apply', { contract_version: 'commons/0.1', idempotency_key: randomUUID(), operations: [{ op: 'create_object', local_ref: 'note', kind: 'note', title: 'Synthetic related work', description: 'Run reference fixture', fields: { content: 'Keep the original evidence.' } }] });
  const workId = linked.local_refs.note;
  const artifact = randomUUID(), missingImage = randomUUID(), run = randomUUID();
  const request = { contract_version: 'commons.capture/1',
    source: { provider: 'manual', namespace: 'synthetic-browser', thread_id: randomUUID() },
    batch_id: randomUUID(), title: 'Synthetic visible conversation',
    coverage: { status: 'partial', messages: 'Three supplied messages', tools: 'One failed tool',
      attachments: 'Text stored; original image unavailable', history: 'From explicit activation', gaps: ['Vendor-client completeness not tested'] },
    items: [
      { id: randomUUID(), source_item_id: 'human', position: 0, kind: 'message', role: 'human', speaker_id: fixture.bob_id,
        source_created_at: '2026-10-16T00:03:00Z', body: 'Compare 3 red parts with 8 blue parts.', artifact_ids: [artifact, missingImage] },
      { id: randomUUID(), source_item_id: 'tool', position: 1, kind: 'tool_result', role: 'tool', tool_name: 'parts_lookup',
        tool_call_id: 'call-1', status: 'failed', body: 'Synthetic timeout. No external service contacted.', artifact_ids: [] },
      { id: randomUUID(), source_item_id: 'answer', position: 2, kind: 'message', role: 'agent',
        body: '<img src=x onerror="window.captureExecuted=true"> Visible reply: lookup failed.', artifact_ids: [] },
    ],
    attachments: [{ id: artifact, artifact: { body: 'Original asymmetric parts: red=3, blue=8', kind: 'text' } },
      { id: missingImage, artifact: { title: 'Missing original diagram', media_type: 'image/png', capture_outcome: 'unavailable', capture_reason: 'Original image bytes were not supplied' } }],
    runs: [{ id: run, source_run_id: 'run-1', kind: 'Synthetic comparison', status: 'failed',
      actor_id: fixture.bob_id, primary_object_id: workId, input: { red: 3, blue: 8 }, trace: [{ tool: 'parts_lookup', status: 'failed' }],
      error: 'Synthetic timeout', result: { available: false }, review: { verdict: 'needs evidence' }, consulted_object_ids: [workId, workId] }],
  };
  const receipt = await call('capture', request);
  const decision = await call('apply', { contract_version: 'commons/0.1', idempotency_key: randomUUID(), operations: [{ op: 'create_object', local_ref: 'note', kind: 'note', title: 'Synthetic linked decision', description: 'Authored connection fixture', fields: { content: 'Decision evidence.' } }] });
  await call('apply', { contract_version: 'commons/0.1', idempotency_key: randomUUID(), operations: [{ op: 'create_connection', from_id: receipt.chat_id, to_id: decision.local_refs.note, from_revision: (await call(`chats/${receipt.chat_id}`)).object.revision, to_revision: 1, kind: 'related_to', explanation: 'Explicitly connected decision.' }] });
  await page.getByRole('button', { name: 'Refresh current view', exact: true }).click();
  await expect(page.getByRole('link', { name: /Synthetic visible conversation/ })).toBeVisible();
  await page.screenshot({ path: info.outputPath('conversations-list.png'), fullPage: true });
  await page.getByRole('link', { name: /Synthetic visible conversation/ }).click();
  await expect(page.getByRole('heading', { name: 'Synthetic visible conversation', exact: true })).toBeVisible();
  await expect(page.getByText('Vendor-client completeness not tested', { exact: true })).not.toBeVisible();
  await page.screenshot({ path: info.outputPath('thread-reading.png') });
  await page.getByText(/^Capture coverage ·/).click();
  await expect(page.getByText('Vendor-client completeness not tested', { exact: true })).toBeVisible();
  await expect(page.getByText('Original image bytes were not supplied', { exact: true })).toBeVisible();
  await call(`artifacts/${missingImage}/content`, undefined, 404);
  await page.getByText('Tool activity · 1 item · failed', { exact: true }).click();
  await expect(page.getByText('tool result · failed', { exact: true })).toBeVisible();
  await expect(page.getByText(request.items[1].body, { exact: true })).not.toBeVisible();
  await page.getByText('Visible tool result details', { exact: true }).click();
  await expect(page.getByText(request.items[1].body, { exact: true })).toBeVisible();
  await expect(page.locator('.stored-text').filter({ hasText: request.items[2].body })).toBeVisible();
  expect(await page.evaluate(() => window.captureExecuted)).toBeUndefined();
  const download = await page.request.get(`/api/artifacts/${artifact}/content`);
  expect(await download.text()).toBe(request.attachments[0].artifact.body);
  await page.screenshot({ path: info.outputPath('conversation-partial.png'), fullPage: true });
  const related = page.getByRole('region', { name: 'Related objects', exact: true });
  await expect(related.getByRole('link', { name: 'Bob Synthetic', exact: true })).toHaveCount(2);
  await expect(related.getByRole('link', { name: 'Synthetic related work', exact: true })).toBeVisible();
  await expect(related.getByRole('link', { name: 'Synthetic linked decision', exact: true })).toBeVisible();
  await related.getByRole('link', { name: 'Synthetic linked decision', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Edit Note title', exact: true })).toBeVisible();
  await page.goBack();
  await expect(page.getByRole('heading', { name: 'Synthetic visible conversation', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Connection map', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Zoom in focused graph', exact: true }).click();
  await page.getByRole('button', { name: 'Fit', exact: true }).click();
  await expect(page.locator('.focused-object-graph .node-label')).toHaveCount(5);
  await page.screenshot({ path: info.outputPath('thread-relationships.png') });
  await related.getByRole('link', { name: 'Synthetic comparison', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Synthetic comparison', exact: true })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Related objects', exact: true }).getByRole('link', { name: 'Synthetic related work', exact: true })).toHaveCount(2);
  await expect(page.getByRole('heading', { name: 'Connection map', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Fit', exact: true }).click();
  await page.screenshot({ path: info.outputPath('run-relationships.png') });
  await page.getByText('Trace · 1 entries', { exact: true }).click();
  await page.getByText('Trace entry 1', { exact: true }).click();
  await expect(page.locator('details').filter({ has: page.getByText('Trace entry 1', { exact: true }) }).getByText(/"tool": "parts_lookup"/)).toBeVisible();
  await expect(page.locator('details').filter({ has: page.getByText('Supplied result', { exact: true }) }).getByText(/"available": false/)).not.toBeVisible();
  await page.getByText('Supplied result', { exact: true }).click();
  await expect(page.locator('details').filter({ has: page.getByText('Supplied result', { exact: true }) }).getByText(/"available": false/)).toBeVisible();
  await page.getByText(/reported · revision 1/).click();
  await expect(page.getByText(/"after_state":/)).toBeVisible();
  await page.screenshot({ path: info.outputPath('run-expanded.png'), fullPage: true });
  const readerContext = await browser.newContext({ baseURL: new URL(page.url()).origin });
  const reader = await readerContext.newPage();
  await login(reader, 'reader');
  await reader.goto(`/chats/${receipt.chat_id}`);
  await expect(reader.locator('.stored-text').filter({ hasText: request.items[0].body })).toBeVisible();
  await expect(reader.getByRole('button', { name: 'Delete thread', exact: true })).toHaveCount(0);
  await readerContext.close();
  await page.getByRole('region', { name: 'Related objects', exact: true }).getByRole('link', { name: 'Synthetic visible conversation', exact: true }).click();
  await page.getByText('Delete managed thread copies', { exact: true }).click();
  const remove = page.getByRole('button', { name: 'Delete thread', exact: true });
  await expect(remove).toBeDisabled();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('heading', { name: 'Synthetic visible conversation', exact: true }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath('conversation-narrow.png'), fullPage: true });
  await page.getByRole('button', { name: 'Fit', exact: true }).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath('thread-map-narrow.png') });
  await page.getByLabel('I understand the managed-copy deletion boundary.').check();
  await remove.click();
  await expect(page.getByText('No threads saved.', { exact: true })).toBeVisible();
  await call(`chats/${receipt.chat_id}`, undefined, 410);
  await call(`runs/${run}`, undefined, 404);
  await call('capture', request, 410);

  const original = 'Read <https://example.test/report|the report> and <http://localhost:2999/objects/old|original Object>.\n\n[Unsafe](javascript:alert(1)) ![Remote](https://example.test/never-load.png)\n<script>window.captureExecuted=true</script>';
  const formatted = await call('capture', { contract_version: 'commons.capture/1', source: { provider: 'slack', namespace: 'synthetic-browser', thread_id: randomUUID() }, batch_id: randomUUID(), title: 'Synthetic stored-format conversation', coverage: { status: 'partial', messages: 'One supplied message', tools: 'None supplied', attachments: 'None supplied', history: 'One batch', gaps: ['Only the supplied message is captured'] }, items: [{ id: randomUUID(), source_item_id: 'formatted', position: 0, kind: 'message', role: 'human', body: original, artifact_ids: [] }] });
  await page.goto(`/chats/${formatted.chat_id}`);
  await expect(page.getByRole('link', { name: 'the report', exact: true })).toHaveAttribute('href', 'https://example.test/report');
  await expect(page.getByRole('link', { name: 'original Object (original local link)', exact: true })).toHaveAttribute('href', 'http://localhost:2999/objects/old');
  await expect(page.locator('.stored-text img, .stored-text script, .stored-text a[href^="javascript:"]')).toHaveCount(0);
  expect(await page.evaluate(() => window.captureExecuted)).toBeUndefined();
  expect((await call(`chats/${formatted.chat_id}`)).items[0].body).toBe(original);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath('conversation-formatted-narrow.png') });
  await page.getByText('Message details', { exact: true }).click();
  await page.getByText('Original message text', { exact: true }).click();
  await expect(page.locator('.conversation-item details pre').first()).toHaveText(original);
});

test('Threads list displays every human and agent participant avatar and links to each User', async ({ page }, info) => {
  await login(page, 'alice');
  const call = async (route, body) => {
    const response = await page.request.fetch(`/api/${route}`, { method: body === undefined ? 'GET' : 'POST',
      headers: { Origin: new URL(page.url()).origin }, ...(body === undefined ? {} : { data: body }) });
    expect(response.status()).toBe(200); return response.json();
  };
  const users = [];
  const pixels = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=', 'base64');
  for (let i = 0; i < 4; i++) {
    const kind = i < 2 ? 'human' : 'agent';
    const user = await call('users', { username: `thread-person-${randomUUID()}`, title: `Thread participant ${i + 1}`,
      user_kind: kind, role: 'member', ...(kind === 'human' ? { password: fixture.password } : {}) });
    const response = await page.request.post(`/api/users/${user.id}/avatar?expected_revision=1&source=Synthetic-test-pixels`, {
      headers: { Origin: new URL(page.url()).origin, 'Content-Type': 'image/png' }, data: pixels });
    expect(response.status()).toBe(200); users.push({ ...user, kind });
  }
  const items = [...users, users[0]].map((user, i) => ({ id: randomUUID(), source_item_id: `participant-${i}`, position: i,
    kind: 'message', role: user.kind === 'human' ? 'human' : 'agent', speaker_id: user.id, source_created_at: null,
    body: `Synthetic message ${i}`, artifact_ids: [] }));
  const receipt = await call('capture', { contract_version: 'commons.capture/1',
    source: { provider: 'manual', namespace: 'synthetic-participants', thread_id: randomUUID() }, batch_id: randomUUID(),
    title: 'Synthetic multi-user thread', coverage: { status: 'partial', messages: 'Five visible messages', tools: 'None',
      attachments: 'None', history: 'Synthetic only', gaps: [] }, items, attachments: [], runs: [] });
  await page.goto('/chats');
  const row = page.locator('.record').filter({ has: page.getByRole('link', { name: 'Open Synthetic multi-user thread', exact: true }) });
  await expect(row.locator('.thread-participants a')).toHaveCount(4);
  for (let i = 0; i < users.length; i++) {
    const link = row.getByRole('link', { name: `Open participant Thread participant ${i + 1}`, exact: true });
    await expect(link).toBeVisible();
    await expect.poll(() => link.locator('img').evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true);
  }
  await page.screenshot({ path: info.outputPath('thread-participant-avatars.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(row.locator('.thread-participants a')).toHaveCount(4);
  for (const link of await row.locator('.thread-participants a').all()) await expect(link).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({ path: info.outputPath('thread-participant-avatars-narrow.png') });
  await row.getByRole('link', { name: 'Open participant Thread participant 4', exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/users/${users[3].id}$`));
  const revision = (await call(`chats/${receipt.chat_id}`)).object.revision;
  await call(`chats/${receipt.chat_id}/delete`, { expected_revision: revision, acknowledge_managed_copy_deletion: true });
});
