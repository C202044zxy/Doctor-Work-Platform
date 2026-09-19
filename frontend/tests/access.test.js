// T07 签收标准 3 and 场景 S1. The rule has to hold on both sides of the app — the
// sidebar drops the entry and the route guard closes the screen — so it lives in
// one table and both read it. These tests pin that table, because the failure it
// guards against is silent: someone edits the route's roles, forgets the menu,
// and S1 fails on "菜单里还有入口" rather than on anything that throws.
import test from 'node:test'
import assert from 'node:assert/strict'

import { canOpen, MODULE_ROLES } from '../src/access.js'

test('a junior may not open the review queue or the audit log', () => {
  assert.equal(canOpen(MODULE_ROLES.review, 'junior'), false)
  assert.equal(canOpen(MODULE_ROLES.audit, 'junior'), false)
})

test('a senior reviews but does not read the audit log', () => {
  // T12 第 3 条 puts /audit behind admin only; a senior is refused as well.
  assert.equal(canOpen(MODULE_ROLES.review, 'senior'), true)
  assert.equal(canOpen(MODULE_ROLES.audit, 'senior'), false)
})

test('an admin may read audit but cannot review clinical records', () => {
  assert.equal(canOpen(MODULE_ROLES.review, 'admin'), false)
  assert.equal(canOpen(MODULE_ROLES.audit, 'admin'), true)
})

test('an ungated screen is open to anyone signed in, and to nobody else', () => {
  // The bug this rules out is defaulting to `[]`, which would hide every screen
  // that never asked for a role — the whole sidebar except two entries.
  assert.equal(canOpen(undefined, 'junior'), true)
  assert.equal(canOpen(undefined, 'senior'), true)
  assert.equal(canOpen(undefined, 'admin'), true)
  // An empty role is an unloaded user, not a superuser.
  assert.equal(canOpen(MODULE_ROLES.audit, ''), false)
})
