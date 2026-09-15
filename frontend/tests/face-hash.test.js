// §2 冲突 1 方案 A: the whole point of hashing rather than "non-empty means
// pass" is 判据⑤/⑥ — a different face has to be refused. These tests pin the two
// properties that make that true: the same image hashes to the same value, and a
// different one lands outside MAX_DISTANCE.
import test from 'node:test'
import assert from 'node:assert/strict'

import { hashBlob, hashDistance, hashSource, HASH_BITS, MAX_DISTANCE } from '../src/face-hash.js'

// A stand-in canvas whose 9×8 pixels alternate according to the source's
// `pattern`: two sources with the same pattern are identical images, and a
// pattern difference of one flips every bit.
function installCanvas() {
  globalThis.document = {
    createElement: () => {
      const canvas = { width: 0, height: 0, source: null }
      canvas.getContext = () => ({
        drawImage: (source) => { canvas.source = source },
        getImageData: () => {
          const data = new Uint8ClampedArray(9 * 8 * 4)
          for (let index = 0; index < 72; index += 1) {
            const value = (index + canvas.source.pattern) % 2 === 0 ? 255 : 0
            data[index * 4] = value
            data[index * 4 + 1] = value
            data[index * 4 + 2] = value
            data[index * 4 + 3] = 255
          }
          return { data }
        },
      })
      return canvas
    },
  }
  globalThis.createImageBitmap = async (blob) => ({ pattern: blob.pattern, close() {} })
}

installCanvas()

test('a hash is 64 bits', () => {
  const hash = hashSource({ pattern: 0 })
  assert.equal(hash.length, HASH_BITS)
  assert.match(hash, /^[01]{64}$/)
})

test('the same photo matches, a different one does not', async () => {
  const enrolled = await hashBlob({ pattern: 3 })
  assert.equal(hashDistance(enrolled, await hashBlob({ pattern: 3 })), 0)
  assert.ok(hashDistance(enrolled, await hashBlob({ pattern: 3 })) <= MAX_DISTANCE)

  const other = hashDistance(enrolled, await hashBlob({ pattern: 4 }))
  assert.equal(other, HASH_BITS)
  assert.ok(other > MAX_DISTANCE)
})

test('a missing hash fails closed rather than matching', () => {
  assert.equal(hashDistance(null, null), HASH_BITS)
  assert.equal(hashDistance('0101', null), HASH_BITS)
  assert.equal(hashDistance('0101', '010'), HASH_BITS)
})
