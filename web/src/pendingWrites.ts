// Keep uncertain writes in memory only. A retry must reuse the exact body and key.
// Weak ownership lets abandoned editor snapshots be collected without persisting content.
export class PendingWrites<T> {
  private owners = new WeakMap<object, Map<string, { key: string; accepted?: T }>>();

  async resolve(owner: object, body: unknown, send: (key: string) => Promise<T>, read: (accepted: T) => Promise<void>): Promise<T> {
    const signature = JSON.stringify(body);
    let pending = this.owners.get(owner);
    if (!pending) { pending = new Map(); this.owners.set(owner, pending); }
    let entry = pending.get(signature);
    if (!entry) { entry = { key: crypto.randomUUID() }; pending.set(signature, entry); }
    // If acknowledgement succeeded but readback failed, retry only the readback.
    if (entry.accepted === undefined) entry.accepted = await send(entry.key);
    await read(entry.accepted);
    pending.delete(signature);
    return entry.accepted;
  }
}
