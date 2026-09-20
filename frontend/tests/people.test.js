// M5. The initials badge is decoration: it never carries anything the name
// beside it does not. That is exactly why it is worth pinning -- a badge that
// draws the wrong letters is a wrong-looking screen nobody checks by hand.
import test from 'node:test'
import assert from 'node:assert/strict'

import { initials } from '../src/people.js'

test('initials takes one letter per word, at most two', () => {
  assert.equal(initials('Zhao Dayong'), 'ZD')
  assert.equal(initials('Wang'), 'W')
})

test('initials survives the blanks a missing name produces', () => {
  assert.equal(initials(''), '')
  assert.equal(initials(undefined), '')
  assert.equal(initials('  Dr   Wang '), 'DW')
})
