import test from 'node:test'
import assert from 'node:assert/strict'
import { saveDraft, readDraft, clearDraft } from '../src/emr-draft.js'

test('failed submissions retain complete drafts across reloads, isolated by account and record', () => {
  const values = new Map()
  const storage = { setItem: (k, v) => values.set(k, v), getItem: k => values.get(k), removeItem: k => values.delete(k) }
  const record = { content_json: { complaint: 'Typed offline', temperature: 37.2 }, version: 2, revision: 4 }
  saveDraft(storage, 3, 12, record)
  assert.deepEqual(readDraft(storage, 3, 12), record)
  assert.equal(readDraft(storage, 4, 12), null)
  assert.equal(readDraft(storage, 3, 13), null)
  clearDraft(storage, 3, 12)
  assert.equal(readDraft(storage, 3, 12), null)
})
