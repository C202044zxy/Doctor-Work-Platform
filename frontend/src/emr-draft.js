// Drafts survive reloads and remain isolated by account and record.
export const draftKey = (userId, recordId) => `dwp.emr.${userId}.${recordId}`
export function saveDraft(storage, userId, recordId, record) {
  storage.setItem(draftKey(userId, recordId), JSON.stringify({
    content_json: record.content_json, version: record.version, revision: record.revision,
  }))
}
export function readDraft(storage, userId, recordId) {
  try { return JSON.parse(storage.getItem(draftKey(userId, recordId)) || 'null') }
  catch { return null }
}
export function clearDraft(storage, userId, recordId) {
  storage.removeItem(draftKey(userId, recordId))
}
