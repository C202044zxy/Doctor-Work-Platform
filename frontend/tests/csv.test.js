// T12 签收标准 2: the export's filename arrives in `Content-Disposition`, and the page
// must not invent its own — the time range it would have to guess is the very thing the
// header exists to state.
//
// This is the one part of the download worth testing. `client.js` drives the DOM and
// cannot be imported here, so the parsing lives in its own module to be reachable.
import test from 'node:test'
import assert from 'node:assert/strict'

import { filenameFromDisposition } from '../src/api/csv.js'

// The header `GET /api/audit-logs/export` actually sends, per the contract's example.
const HEADER =
  'attachment; filename="audit-2026-09-01_2026-09-11.csv"; ' +
  "filename*=UTF-8''audit-2026-09-01_2026-09-11.csv"

test('reads the filename out of both spellings', () => {
  assert.equal(filenameFromDisposition(HEADER), 'audit-2026-09-01_2026-09-11.csv')
  assert.equal(
    filenameFromDisposition('attachment; filename="audit-2026-09-01_2026-09-11.csv"'),
    'audit-2026-09-01_2026-09-11.csv',
  )
  assert.equal(
    filenameFromDisposition("attachment; filename*=UTF-8''audit-2026-09-01_2026-09-11.csv"),
    'audit-2026-09-01_2026-09-11.csv',
  )
})

test('prefers the encoded spelling when the two disagree', () => {
  // RFC 5987 exists because a bare `filename` cannot carry non-ASCII, so when both are
  // present the encoded one is the one that survived encoding intact.
  assert.equal(
    filenameFromDisposition(
      "attachment; filename=\"audit.csv\"; filename*=UTF-8''%E5%AE%A1%E8%AE%A1-2026.csv",
    ),
    '审计-2026.csv',
  )
})

test('an absent or unusable header returns null rather than a guess', () => {
  // Null is what lets the caller fall back deliberately; an empty string would be handed
  // to `link.download` and produce a file with no name at all.
  assert.equal(filenameFromDisposition(null), null)
  assert.equal(filenameFromDisposition(''), null)
  assert.equal(filenameFromDisposition('attachment'), null)
  // The disposition does not have to be `attachment` to be worth reading.
  assert.equal(filenameFromDisposition('inline; filename="audit.csv"'), 'audit.csv')
})

test('a malformed escape falls back to the plain parameter', () => {
  // `decodeURIComponent` throws on a lone `%`. A download is not worth failing over, and
  // the plain parameter is still readable.
  assert.equal(
    filenameFromDisposition("attachment; filename=\"plain.csv\"; filename*=UTF-8''%E0%A4%A"),
    'plain.csv',
  )
})
