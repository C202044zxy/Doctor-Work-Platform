import { accessToken } from '../session'

export async function workRequest(path, method = 'GET', body) {
  const form = body instanceof FormData
  const response = await fetch(path, {
    method,
    headers: { Authorization: `Bearer ${accessToken()}`, ...(!form && body !== undefined ? { 'Content-Type': 'application/json' } : {}) },
    body: body === undefined ? undefined : form ? body : JSON.stringify(body),
  })
  const result = await response.json()
  if (!response.ok) throw new Error(result.message || 'Request failed')
  return result.data
}
export const work = (path, method, body) => workRequest(`/api${path}`, method, body)
export async function imageBlob(url) {
  const response = await fetch(url, { headers: { Authorization: `Bearer ${accessToken()}` } })
  if (!response.ok) throw new Error('Image unavailable or access denied')
  return URL.createObjectURL(await response.blob())
}
export function mergeMessages(current, incoming) {
  const rows = new Map(current.map(row => [row.id, row]))
  incoming.forEach(row => rows.set(row.id, row))
  return [...rows.values()].sort((a, b) => a.id - b.id)
}
