import { test, expect, fixture, login, api, apply } from './fixtures.mjs';

test('canonical rows, modal focus, Note autosave/cancel and narrow navigation use real records', async ({ page, request, context }, info) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await login(page);
  await page.getByRole('button', { name: 'Notes', exact: true }).click();
  const newNote = page.getByRole('button', { name: 'New note', exact: true });
  await newNote.click();
  await expect(page.getByLabel('Title', { exact: true })).toBeFocused();
  await page.getByRole('button', { name: 'Create note', exact: true }).focus();
  await page.keyboard.press('Tab');
  await expect(page.getByRole('button', { name: 'Close', exact: true })).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(newNote).toBeFocused();
  await newNote.click();
  await page.getByLabel('Title', { exact: true }).fill('Synthetic banksia note');
  await page.getByLabel('Content', { exact: true }).fill('Caller-supplied draft.');
  await page.getByRole('button', { name: 'Create note', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Synthetic banksia note', exact: true })).toBeVisible();
  const id = (await api(request, 'objects?q=banksia')).objects[0].id;
  await page.getByRole('button', { name: 'Edit Note content', exact: true }).click();
  await page.getByLabel('Note content', { exact: true }).fill('Revised synthetic evidence, saved without a submit click.');
  await expect.poll(async () => (await api(request, `objects/${id}`)).object.fields.content).toBe('Revised synthetic evidence, saved without a submit click.');
  await page.getByRole('button', { name: 'Edit Note title', exact: true }).click();
  await page.getByLabel('Note title', { exact: true }).fill('Cancelled draft');
  await page.keyboard.press('Escape');
  await expect(page.getByRole('heading', { name: 'Synthetic banksia note', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Notes', exact: true }).first().click();
  const link = page.getByRole('link', { name: 'Open Synthetic banksia note', exact: true });
  await expect(link).toHaveAttribute('href', `/objects/${id}`);
  await page.getByRole('button', { name: `Copy Object ID ${id}`, exact: true }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(id);
  await expect(page).toHaveURL(/\/notes$/);
  await page.getByRole('button', { name: 'Collapse navigation', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Expand navigation', exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(async () => (await page.locator('.main-panel').boundingBox()).x).toBe(56);
  const panelBounds = await page.locator('.main-panel').boundingBox();
  await page.getByRole('button', { name: 'Expand navigation', exact: true }).click();
  await expect(page.locator('.brand-name')).toBeVisible();
  await expect(page.getByRole('navigation').getByRole('button', { name: 'Notes', exact: true })).toHaveCSS('font-size', '14px');
  expect(await page.locator('.main-panel').boundingBox()).toEqual(panelBounds);
  await newNote.focus();
  await expect(newNote).not.toBeFocused();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('button', { name: 'Expand navigation', exact: true })).toBeFocused();
  await page.keyboard.press('Enter');
  await page.getByRole('button', { name: 'Close navigation', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Expand navigation', exact: true })).toBeFocused();
  await page.keyboard.press('Enter');
  await page.getByRole('navigation').getByRole('button', { name: 'Notes', exact: true }).click();
  await expect(page.locator('.brand-name')).not.toBeVisible();
  await link.click();
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Synthetic banksia note', exact: true })).toBeVisible();
  expect((await api(request, `objects/${id}`)).object.revision).toBe(2);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath('narrow-note.png') });
  await page.getByRole('button', { name: 'Notes', exact: true }).first().click();
  await page.getByLabel('Search notes', { exact: true }).fill('no-synthetic-record-matches-this');
  await expect(page.getByText('No active objects match your search.', { exact: true })).toBeVisible();
  await page.screenshot({ path: info.outputPath('narrow-empty.png') });
  await page.goto('/objects/00000000-0000-0000-0000-000000000000');
  await expect(page.getByRole('alert')).toContainText('Could not load');
  await page.getByRole('button', { name: 'Entities', exact: true }).click();
  await page.getByRole('button', { name: 'New entity', exact: true }).click();
  await page.getByLabel('Title', { exact: true }).fill('Synthetic wattle organisation');
  await page.getByLabel('Kind', { exact: true }).fill('organisation');
  await page.getByRole('button', { name: 'Create entity', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Synthetic wattle organisation', exact: true })).toBeVisible();
  expect((await api(request, 'objects?q=wattle')).objects[0].fields.entity_kind).toBe('organisation');
});

test('real explained graph selects connected records and opens connection endpoints', async ({ page, request }, info) => {
  const memoryTitle = 'Synthetic acacia decision WWWWWWWWWWWWW';
  const noteTitle = 'Synthetic acacia evidence WWWWWWWWWWWWW';
  const created = await apply(request, [
    { op: 'create_object', local_ref: 'memory', kind: 'memory', title: memoryTitle, description: 'A graph fixture.', fields: {} },
    { op: 'create_object', local_ref: 'note', kind: 'note', title: noteTitle, description: 'Supporting note.', fields: {} },
  ]);
  await apply(request, [{ op: 'create_connection', from_id: created.local_refs.memory, to_id: created.local_refs.note,
    from_revision: 1, to_revision: 1, kind: 'derived_from', explanation: 'The synthetic note supports this decision.' }]);
  await login(page);
  await page.getByRole('combobox', { name: 'Sort Objects', exact: true }).selectOption('connected');
  await page.getByRole('link', { name: `Open ${memoryTitle}`, exact: true }).click();
  await page.getByRole('link', { name: 'Connection', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'derived from', exact: true })).toBeVisible();
  await expect(page.locator('.page-path strong')).toHaveText(`${memoryTitle} → ${noteTitle}`);
  await expect(page.getByRole('link', { name: `Open Object ID ${created.local_refs.note}`, exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Connections', exact: true }).first().click();
  await page.getByLabel('Search graph Objects', { exact: true }).fill('Synthetic acacia decision');
  await page.getByRole('button', { name: 'Focus', exact: true }).click();
  await expect(page.getByRole('heading', { name: memoryTitle, exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Zoom in', exact: true }).click();
  await page.getByRole('button', { name: 'Fit', exact: true }).click();
  await page.screenshot({ path: info.outputPath('connected-graph.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/objects/${created.local_refs.memory}`);
  const graph = page.getByRole('region', { name: `Connection map for ${memoryTitle}`, exact: true });
  await expect(graph.locator('svg text')).toHaveCount(2);
  const labelsFit = await graph.locator('svg').evaluate(svg => {
    const bounds = svg.getBoundingClientRect();
    return [...svg.querySelectorAll('text')].every(label => {
      const box = label.getBoundingClientRect();
      return box.left >= bounds.left && box.right <= bounds.right;
    });
  });
  expect(labelsFit, 'Fit keeps even wide-character labels inside the narrow graph').toBe(true);
});

test.describe('built-in Task views', () => {
  test.use({ timezoneId: 'Australia/Sydney' });

  test('List/date and Board share filters, completed visibility and URL navigation', async ({ page, request }, info) => {
    // Sydney changes from UTC+10 to UTC+11 during this local day. UTC-day or
    // fixed-24-hour grouping puts the early/late/tomorrow cases in wrong groups.
    await page.clock.setFixedTime(new Date('2026-10-03T14:05:00Z'));
    const cases = [
      ['overdue', '2026-10-03T13:59:00Z', 'todo', 'orchid'],
      ['early', '2026-10-03T14:01:00Z', 'doing', 'orchid'],
      ['late', '2026-10-04T12:59:00Z', 'review', 'orchid'],
      ['tomorrow', '2026-10-04T13:01:00Z', 'todo', 'orchid'],
      ['completed', '2026-10-03T14:01:00Z', 'done', 'orchid'],
      ['other-project', '2026-10-03T14:01:00Z', 'todo', 'wattle'],
    ];
    const created = await apply(request, cases.map(([name, due_at, status, project], index) => ({
      op: 'create_object', local_ref: name, kind: 'task', title: `Synthetic modular ${name}`,
      description: 'Synthetic Task view acceptance.', fields: { status, due_at, priority: 'high',
        owner_object_id: fixture.bob_id, work_kind: 'general',
        github_issue_url: `https://github.com/synthetic/commons/issues/${200 + index}`,
        brief_markdown: `Project: ${project}\n\nCheck the synthetic outcome.` },
    })));
    await login(page);
    await page.getByRole('button', { name: 'Tasks', exact: true }).click();
    await expect(page.getByRole('button', { name: 'List', exact: true })).toHaveAttribute('aria-pressed', 'true');
    await page.getByLabel('Search tasks', { exact: true }).fill('Synthetic modular');
    await expect(page.getByRole('link', { name: /^Open Synthetic modular/ })).toHaveCount(5);
    await page.getByLabel('Filter task projects', { exact: true }).selectOption('orchid');
    await page.getByLabel('Sort Tasks', { exact: true }).selectOption('due_date');
    await expect(page.getByRole('region', { name: 'Overdue tasks', exact: true }).getByRole('link', { name: 'Open Synthetic modular overdue', exact: true })).toBeVisible();
    await expect(page.getByRole('region', { name: 'Today tasks', exact: true }).getByRole('link', { name: /^Open Synthetic modular/ })).toHaveCount(2);
    await expect(page.getByRole('region', { name: 'Tomorrow tasks', exact: true }).getByRole('link', { name: 'Open Synthetic modular tomorrow', exact: true })).toBeVisible();
    await expect(page.getByRole('link', { name: /^Open Synthetic modular/ })).toHaveCount(4);
    await page.screenshot({ path: info.outputPath('task-date-list.png') });
    await page.getByRole('button', { name: 'Board', exact: true }).click();
    await expect(page).toHaveURL(/\/tasks\?view=kanban$/);
    await expect(page.getByLabel('Search tasks', { exact: true })).toHaveValue('Synthetic modular');
    await expect(page.getByLabel('Filter task projects', { exact: true })).toHaveValue('orchid');
    await expect(page.getByRole('link', { name: /^Open Synthetic modular/ })).toHaveCount(4);
    await page.getByRole('button', { name: 'Show completed', exact: true }).click();
    await expect(page.getByRole('region', { name: 'Done tasks', exact: true }).getByRole('link', { name: 'Open Synthetic modular completed', exact: true })).toBeVisible();
    await page.screenshot({ path: info.outputPath('task-board.png') });
    await page.getByRole('button', { name: 'List', exact: true }).click();
    await expect(page.getByLabel('Sort Tasks', { exact: true })).toHaveValue('due_date');
    await expect(page.getByRole('region', { name: 'Completed tasks', exact: true })).toContainText('Synthetic modular completed');
    await page.goBack();
    await expect(page.getByRole('button', { name: 'Board', exact: true })).toHaveAttribute('aria-pressed', 'true');
    await page.goForward();
    await expect(page.getByRole('button', { name: 'List', exact: true })).toHaveAttribute('aria-pressed', 'true');
    await page.goBack();
    await page.reload();
    await expect(page.getByRole('region', { name: 'Task board', exact: true })).toHaveAttribute('aria-busy', 'false');
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await expect(page.getByRole('button', { name: 'List', exact: true })).toBeInViewport();
    await page.screenshot({ path: info.outputPath('task-board-narrow.png') });
    await page.goto('/tasks?view=removed');
    await expect(page.getByRole('status').filter({ hasText: 'This view is unavailable.' })).toContainText('This view is unavailable. Showing the list.');
    await expect(page.getByRole('button', { name: 'List', exact: true })).toHaveAttribute('aria-pressed', 'true');
    await page.getByLabel('Search tasks', { exact: true }).fill('no-modular-task-matches');
    await expect(page.getByText('No active objects match your search.', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Board', exact: true }).click();
    await expect(page.getByRole('status')).toHaveText('No tasks match this view.');
    for (const id of Object.values(created.local_refs)) expect((await api(request, `objects/${id}`)).object.revision).toBe(1);
  });

  test('Board moves save real state, reject stale/invalid writes and respect readers', async ({ page, request }, info) => {
    const fields = { status: 'todo', priority: 'high', owner_object_id: fixture.bob_id,
      due_at: '2027-04-03T04:25:00Z', work_kind: 'code',
      github_issue_url: 'https://github.com/synthetic/commons/issues/3', brief_markdown: 'Check synthetic delivery.' };
    const created = await apply(request, [
      { op: 'create_object', local_ref: 'move', kind: 'task', title: 'Synthetic kanban delivery', description: 'Status move fixture.', fields },
      { op: 'create_object', local_ref: 'unbriefed', kind: 'task', title: 'Synthetic kanban unbriefed', description: 'Must not enter doing.', fields: { ...fields, github_issue_url: 'https://github.com/synthetic/commons/issues/4', brief_markdown: '' } },
    ]);
    const id = created.local_refs.move;
    const read = async () => (await api(request, `objects/${id}`)).object;
    await login(page);
    await page.goto('/tasks?view=kanban');
    const link = page.getByRole('link', { name: 'Open Synthetic kanban delivery', exact: true });
    const move = page.getByLabel('Move Synthetic kanban delivery', { exact: true });
    await expect(move).toBeEnabled();
    await link.locator('..').dragTo(page.getByRole('region', { name: 'In progress tasks', exact: true }).locator('header'));
    await expect.poll(async () => (await read()).fields.status).toBe('doing');
    await expect(page.getByRole('region', { name: 'In progress tasks', exact: true }).getByRole('link', { name: 'Open Synthetic kanban delivery', exact: true })).toBeVisible();
    await expect(move).toBeEnabled();
    const current = await read();
    await apply(request, [{ op: 'update_object', object_id: id, expected_revision: current.revision,
      title: current.title, description: 'External winner.', fields: { ...current.fields, status: 'review' } }]);
    await move.selectOption('done');
    await expect(page.getByRole('alert')).toContainText('revision conflict; reload before editing');
    await expect(page.getByRole('region', { name: 'In progress tasks', exact: true }).getByRole('link', { name: 'Open Synthetic kanban delivery', exact: true })).toBeVisible();
    expect((await read()).fields.status).toBe('review');
    await page.screenshot({ path: info.outputPath('task-board-conflict.png') });
    await page.getByRole('button', { name: 'Reload tasks', exact: true }).click();
    await expect(move).toHaveValue('review');
    await move.focus();
    await move.selectOption('blocked');
    const dialog = page.getByRole('dialog', { name: 'Block “Synthetic kanban delivery”', exact: true });
    await expect(dialog.getByLabel('Blocked reason', { exact: true })).toBeFocused();
    await expect(dialog.getByRole('button', { name: 'Block task', exact: true })).toBeDisabled();
    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
    await expect(move).toBeFocused();
    await move.selectOption('blocked');
    await page.getByLabel('Blocked reason', { exact: true }).fill('Waiting for synthetic approval.');
    await page.screenshot({ path: info.outputPath('task-board-blocked-dialog.png') });
    await page.getByRole('button', { name: 'Block task', exact: true }).click();
    await expect.poll(async () => (await read()).fields.blocked_reason).toBe('Waiting for synthetic approval.');
    await expect(move).toHaveValue('blocked');
    await move.selectOption('done');
    await expect(link).toHaveCount(0);
    const done = await read();
    expect(done.fields).toMatchObject({ ...fields, status: 'done', blocked_reason: null });
    expect(Number.isFinite(Date.parse(done.fields.completed_at))).toBe(true);
    await page.getByRole('button', { name: 'Show completed', exact: true }).click();
    await expect(move).toHaveValue('done');
    await move.selectOption('todo');
    await expect.poll(async () => (await read()).fields.completed_at).toBeNull();
    await page.getByLabel('Move Synthetic kanban unbriefed', { exact: true }).selectOption('doing');
    await expect(page.getByRole('alert')).toContainText('Task brief required before doing');
    expect((await api(request, `objects/${created.local_refs.unbriefed}`)).object.revision).toBe(1);
    await page.getByRole('button', { name: 'List', exact: true }).click();
    await link.click();
    await expect(page.getByLabel('Task status', { exact: true })).toHaveValue('todo');
    await expect(page.getByText('External winner.', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Sign out', exact: true }).click();
    await login(page, 'reader');
    await page.goto('/tasks?view=kanban');
    await expect(move).toBeDisabled();
    await expect(link.locator('..')).toHaveAttribute('draggable', 'false');
    const before = await read();
    const denied = await page.evaluate(async object => (await fetch('/api/apply', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
        contract_version: 'commons/0.1', idempotency_key: crypto.randomUUID(), operations: [
          { op: 'update_object', object_id: object.id, expected_revision: object.revision,
            title: object.title, description: object.description, fields: { ...object.fields, status: 'done' } },
        ],
      }),
    })).status, before);
    expect(denied).toBe(403);
    expect(await read()).toEqual(before);
  });
});

test('agent Users, scoped identity and image avatars follow Task ownership across views', async ({ page, request }, info) => {
  await login(page, 'alice');
  await page.goto('/access');
  await page.getByRole('combobox', { name: 'User kind', exact: true }).selectOption('agent');
  await expect(page.getByLabel('Password', { exact: true })).toHaveCount(0);
  await page.getByLabel('Username', { exact: true }).fill('puck-ui');
  await page.getByLabel('Display name', { exact: true }).fill('Puck Synthetic');
  await page.getByRole('button', { name: 'Create user', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('User created.');
  const puck = (await api(request, 'users')).users.find(user => user.title === 'Puck Synthetic');
  expect(puck.fields.user_kind).toBe('agent');
  const image = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=', 'base64');
  for (const id of [puck.id, fixture.bob_id]) {
    await page.getByRole('combobox', { name: 'Avatar user', exact: true }).selectOption(id);
    await page.getByLabel('Avatar image', { exact: true }).setInputFiles({ name: 'synthetic.png', mimeType: 'image/png', buffer: image });
    await page.getByLabel('Image source / permission', { exact: true }).fill('Synthetic test pixels, no personal media.');
    await page.getByRole('button', { name: 'Upload avatar', exact: true }).click();
    await expect(page.getByRole('status')).toHaveText('Avatar saved.');
    await expect.poll(async () => (await api(request, `objects/${id}`)).object.revision).toBe(2);
  }
  await page.getByRole('combobox', { name: 'Credential identity', exact: true }).selectOption(puck.id);
  await page.getByLabel('Label', { exact: true }).fill('Synthetic Puck UI writer');
  await page.getByRole('checkbox', { name: 'task', exact: true }).check();
  await page.getByRole('button', { name: 'Create credential', exact: true }).click();
  await expect(page.getByLabel('New agent token', { exact: true })).toBeVisible();
  const token = await page.getByLabel('New agent token', { exact: true }).inputValue();
  await page.getByRole('button', { name: 'Dismiss secret', exact: true }).click();
  expect((await api(request, 'me', undefined, token)).id).toBe(puck.id);
  const created = await apply(request, [puck.id, fixture.bob_id].map((owner, index) => ({
    op: 'ensure_task', local_ref: String(index), title: `Synthetic avatar ${index ? 'human' : 'agent'} work`, description: 'The linked Issue owns acceptance.',
    fields: { status: 'todo', priority: 'medium', owner_object_id: owner, due_at: '2026-10-16T23:59:59+11:00',
      work_kind: 'code', github_issue_url: `https://github.com/synthetic/commons/issues/${510 + index}`, brief_markdown: 'Project: avatars\n\nCheck the agreed outcome.' },
  })), token);
  const agentTask = created.local_refs['0'];
  const humanTask = created.local_refs['1'];
  expect((await api(request, `objects/${humanTask}`)).audit_events[0].actor_id).toBe(puck.id);
  await apply(request, [{ op: 'create_connection', from_id: agentTask, to_id: humanTask, from_revision: 1, to_revision: 1,
    kind: 'related_to', explanation: 'Synthetic agent and human handoff.' }]);
  await page.goto('/tasks');
  await page.getByLabel('Search tasks', { exact: true }).fill('Synthetic avatar');
  const avatar = (name, kind) => page.getByRole('img', { name: `${name}, ${kind}, owner`, exact: true });
  const loaded = async locator => {
    await expect(locator.locator('img')).toHaveCount(1);
    await expect.poll(() => locator.locator('img').evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true);
  };
  await loaded(avatar('Puck Synthetic', 'Agent'));
  await loaded(avatar('Bob Synthetic', 'Human'));
  await page.screenshot({ path: info.outputPath('avatar-list.png') });
  await page.getByLabel('Sort Tasks', { exact: true }).selectOption('due_date');
  await loaded(avatar('Puck Synthetic', 'Agent'));
  await page.screenshot({ path: info.outputPath('avatar-due.png') });
  await page.getByRole('button', { name: 'Board', exact: true }).click();
  await loaded(avatar('Puck Synthetic', 'Agent'));
  await loaded(avatar('Bob Synthetic', 'Human'));
  await page.getByLabel('Move Synthetic avatar agent work', { exact: true }).selectOption('review');
  await expect.poll(async () => (await api(request, `objects/${agentTask}`)).object.fields.status).toBe('review');
  expect((await api(request, `objects/${agentTask}`)).object.fields.owner_object_id).toBe(puck.id);
  await loaded(avatar('Puck Synthetic', 'Agent'));
  await page.screenshot({ path: info.outputPath('avatar-board.png') });
  await page.getByRole('link', { name: 'Open Synthetic avatar agent work', exact: true }).click();
  await loaded(avatar('Puck Synthetic', 'Agent'));
  await loaded(avatar('Bob Synthetic', 'Human'));
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath('avatar-detail-narrow.png') });
  // Real corrupted raster response exercises fallback, then a new URL must recover.
  let user = (await api(request, `objects/${puck.id}`)).object;
  const upload = async buffer => {
    const response = await page.request.post(`/api/users/${puck.id}/avatar?expected_revision=${user.revision}&source=Synthetic`,
      { headers: { Origin: new URL(page.url()).origin, 'Content-Type': 'image/png' }, data: buffer });
    expect(response.status()).toBe(200);
    user = (await api(request, `objects/${puck.id}`)).object;
    await page.getByRole('button', { name: 'Refresh current view', exact: true }).click();
  };
  await upload(image.subarray(0, 8));
  await expect(avatar('Puck Synthetic', 'Agent')).toHaveText('PS');
  await upload(image);
  await loaded(avatar('Puck Synthetic', 'Agent'));
  await page.goto('/tasks');
  await page.getByLabel('Search tasks', { exact: true }).fill('Synthetic avatar');
  await expect(avatar('Puck Synthetic', 'Agent')).toBeVisible();
  await expect(avatar('Bob Synthetic', 'Human')).toBeVisible();
  await page.screenshot({ path: info.outputPath('avatar-list-narrow.png') });
  await page.getByLabel('Sort Tasks', { exact: true }).selectOption('due_date');
  await expect(avatar('Puck Synthetic', 'Agent')).toBeVisible();
  await expect(avatar('Bob Synthetic', 'Human')).toBeVisible();
  await page.screenshot({ path: info.outputPath('avatar-date-narrow.png') });
  await page.goto('/users');
  await expect(page.getByRole('img', { name: 'Puck Synthetic, Agent, identity', exact: true })).toBeVisible();
  await expect(page.getByRole('img', { name: 'Bob Synthetic, Human, identity', exact: true })).toBeVisible();
  await page.screenshot({ path: info.outputPath('avatar-users-narrow.png') });
});


test('record collections load the first page and continue only on request', async ({ page, request }, info) => {
  const prefix = 'paginationcobaltfixture';
  const ids = [];
  for (let start = 0; start < 51; start += 50) {
    const operations = Array.from({ length: Math.min(50, 51-start) }, (_, n) => ({
      op: 'create_object', local_ref: `r${start+n}`, kind: 'memory',
      title: `${prefix} ${start+n}`, description: 'Synthetic pagination acceptance.', fields: {},
    }));
    const receipt = await apply(request, operations);
    ids.push(...Object.values(receipt.local_refs));
  }
  try {
    await login(page);
    await page.getByRole('button', { name: 'Memories', exact: true }).click();
    const collectionRequests = [];
    page.on('request', request => {
      const url = new URL(request.url());
      if (url.pathname === '/api/objects' && url.searchParams.get('q') === prefix) collectionRequests.push(url);
    });
    await page.getByLabel('Search memories', { exact: true }).fill(prefix);
    await expect(page.getByText('50 of 51 records loaded', { exact: true })).toBeVisible();
    await expect(page.getByLabel('51 records', { exact: true })).toBeVisible();
    expect(collectionRequests.map(url => url.searchParams.get('offset'))).toEqual(['0']);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole('button', { name: 'Load more records', exact: true }).scrollIntoViewIfNeeded();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: info.outputPath('pagination-control-narrow.png') });
    await page.getByRole('button', { name: 'Load more records', exact: true }).click();
    await expect(page.locator('.record-open')).toHaveCount(51);
    await expect(page.getByRole('button', { name: 'Load more records', exact: true })).toHaveCount(0);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: info.outputPath('paged-records-narrow.png') });
    const graphOffsets = [];
    page.on('request', req => {
      const url = new URL(req.url());
      if (url.pathname === '/api/objects') graphOffsets.push(Number(url.searchParams.get('offset')));
    });
    await page.getByRole('button', { name: 'Connections', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Load more map', exact: true })).toBeVisible();
    expect(graphOffsets).toEqual([0]);
    await expect(page.getByText(/Search and clusters cover this map only/)).toBeVisible();
    await page.screenshot({ path: info.outputPath('partial-map-control-narrow.png') });
    await page.getByRole('button', { name: 'Load more map', exact: true }).click();
    await expect.poll(() => graphOffsets).toEqual([0, 50]);
    await page.screenshot({ path: info.outputPath('partial-map-narrow.png'), fullPage: true });
  } finally {
    for (let start = 0; start < ids.length; start += 50) await apply(request, ids.slice(start,start+50).map(id => ({
      op:'set_lifecycle', object_id:id, expected_revision:1, archived:true, protected:false,
    })));
  }
});

test('record overview omits evidence bodies and loads only the opened artifact and history', async ({ page, request }, info) => {
  const created = await apply(request, [{ op: 'create_object', local_ref: 'record', kind: 'memory', title: 'Synthetic lazy evidence', description: 'Evidence loading acceptance.', fields: {} }]);
  const id = created.local_refs.record;
  const marker = 'LAZY-EVIDENCE-SYNTHETIC-';
  for (let revision = 1; revision <= 3; revision++) {
    await apply(request, [{ op: 'append_artifact', object_id: id, expected_revision: revision, body: marker + String(revision) + '\n' + 'bounded fixture '.repeat(2000) }]);
  }
  const full = await api(request, `objects/${id}`);
  await login(page);
  const reads = [], overviews = [];
  page.on('request', req => {
    const url = new URL(req.url());
    if (/^\/api\/(artifacts|history)\//.test(url.pathname)) reads.push(url.pathname);
    if (url.pathname === `/api/objects/${id}`) overviews.push(url);
  });
  const overview = page.waitForResponse(response => new URL(response.url()).pathname === `/api/objects/${id}`);
  await page.goto(`/objects/${id}`);
  await expect(page.getByRole('heading', { name: 'Synthetic lazy evidence', exact: true })).toBeVisible();
  const payload = await (await overview).json();
  expect(payload.view).toBe('compact');
  expect(JSON.stringify(payload)).not.toContain(marker);
  expect(reads).toEqual([]);
  const aid = full.artifacts[0].id;
  await page.locator(`a[href$="/artifacts/${aid}"]`).first().click();
  await expect(page.getByText(marker + '1', { exact: false }).first()).toBeVisible();
  expect(reads).toEqual([`/api/artifacts/${aid}`]);
  await page.getByRole('button', { name: 'Close reader', exact: true }).click();
  await page.getByText(/^Revision history \(/).click();
  expect(reads.filter(path => path.startsWith('/api/history/'))).toEqual([]);
  await page.locator('summary').filter({ hasText: /^Revision 1 ·/ }).click();
  await expect(page.getByRole('heading', { name: 'After', exact: true })).toBeVisible();
  expect(reads.filter(path => path.startsWith('/api/history/'))).toHaveLength(1);
  expect(overviews.every(url => url.searchParams.get('view') === 'compact')).toBe(true);
  await page.screenshot({ path: info.outputPath('lazy-history.png'), fullPage: true });
});
