import { test } from 'node:test';
import assert from 'node:assert/strict';
import { PendingWrites } from '../../web/src/pendingWrites.ts';

test('commit with lost acknowledgement reuses key and exact body identity', async () => {
  const pending = new PendingWrites(), owner = {}, body = { revision: 4, title: 'Synthetic' };
  const keys = [], receipts = new Map();
  const send = async key => {
    keys.push(key);
    if (!receipts.has(key)) { receipts.set(key, { revision: 5 }); throw new Error('response lost'); }
    return receipts.get(key);
  };
  await assert.rejects(pending.resolve(owner, body, send, async () => {}), /lost/);
  assert.deepEqual(await pending.resolve(owner, { ...body }, send, async () => {}), { revision: 5 });
  assert.equal(keys[0], keys[1]); assert.equal(receipts.size, 1);
});

test('readback outage retries read only; changed body and owner get distinct keys', async () => {
  const pending = new PendingWrites(), owner = {}, keys = [];
  const send = async key => { keys.push(key); return { revision: 2 }; };
  await assert.rejects(pending.resolve(owner, { title: 'a' }, send, async () => { throw new Error('read failed'); }));
  await pending.resolve(owner, { title: 'a' }, send, async () => {});
  assert.equal(keys.length, 1);
  await assert.rejects(pending.resolve(owner, { title: 'b' }, send, async () => { throw new Error('conflict'); }));
  await pending.resolve({}, { title: 'b' }, send, async () => {});
  assert.equal(new Set(keys).size, 3);
});
