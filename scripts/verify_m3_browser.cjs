// Optional browser integration check. Requires Playwright and installed Edge.
// Run after scripts/dev.ps1. Uses synthetic media, not a physical camera.
// PLAYWRIGHT_MODULE_PATH may point to an existing Playwright installation.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const { execFileSync } = require('node:child_process')
const path = require('node:path')
const fs = require('node:fs')
const assert = require('node:assert/strict')

const root = path.resolve(__dirname, '..')
const backend = path.join(root, 'backend')
const python = path.join(backend, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')
const base = process.env.M3_BASE_URL || 'http://127.0.0.1:5173'
const token = name => execFileSync(python, ['-m', 'app.dev_session', '--username', name], { cwd: backend, encoding: 'utf8' }).trim()

async function main() {
  let contexts = []
  const browser = await chromium.launch({
    channel: 'msedge', headless: true,
    args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', '--autoplay-policy=no-user-gesture-required'],
  })
  try {
    contexts = await Promise.all(['dr_wang', 'dr_li'].map(async name => {
      const jwt = token(name)
      const context = await browser.newContext({ permissions: ['camera', 'microphone'], viewport: { width: 1440, height: 1000 } })
      await context.addInitScript(value => localStorage.setItem('dwp.access-token', value), jwt)
      return { context, jwt, page: await context.newPage() }
    }))
    const [a, b] = contexts
    const api = async (identity, endpoint, body) => {
      const response = await identity.context.request.fetch(`${base}/api${endpoint}`, {
        method: body === undefined ? 'GET' : 'POST',
        headers: { Authorization: `Bearer ${identity.jwt}` }, ...(body === undefined ? {} : { data: body }),
      })
      assert.equal(response.status(), 200, await response.text())
      return (await response.json()).data
    }
    const room = await api(a, '/consultations', { patient_no: 'P20260001' })
    await api(b, `/consultations/${room.id}/accept`, {})
    const errors = []
    for (const identity of contexts) identity.page.on('pageerror', error => errors.push(error.message))
    await Promise.all(contexts.map(({ page }) => page.goto(`${base}/consultations?room=${room.id}`)))
    await Promise.all(contexts.map(({ page }) => page.getByText('active · Connected', { exact: true }).waitFor()))
    const message = `M3 browser check ${Date.now()}`
    await a.page.getByPlaceholder('Write a message').fill(message)
    await a.page.getByRole('button', { name: 'Send', exact: true }).click()
    await b.page.locator('.bubble').filter({ hasText: message }).waitFor()
    await a.page.locator('.bubble').filter({ hasText: message }).getByText('Delivered', { exact: false }).waitFor()
    await a.page.getByRole('button', { name: 'Start video call' }).click()
    await b.page.getByRole('button', { name: 'Answer', exact: true }).click()
    await Promise.all(contexts.map(({ page }) => page.getByText('Video: connected', { exact: true }).waitFor({ timeout: 30000 })))
    for (const { page } of contexts) {
      await page.waitForFunction(() => {
        const remote = document.querySelectorAll('.video-call video')[1]
        return remote?.videoWidth > 0 && remote.srcObject?.getAudioTracks().length > 0
      })
    }
    console.log('PASS: two isolated sessions, persisted text, bidirectional synthetic WebRTC video/audio tracks')
    await a.page.getByRole('button', { name: 'Hang up', exact: true }).click()
    await b.page.getByText('Call ended: hangup.', { exact: true }).waitFor()
    await a.page.getByText('Call history (1)', { exact: true }).waitFor()
    const calls = await api(a, `/consultations/${room.id}/calls`)
    assert.equal(calls.total, 1)
    assert.ok(calls.items[0].connected_at && calls.items[0].ended_at)
    await a.page.getByRole('button', { name: 'End consultation', exact: true }).click()
    await b.page.getByText('This conversation is read-only.', { exact: true }).waitFor()
    assert.equal(await b.page.getByRole('button', { name: 'Send', exact: true }).isDisabled(), true)
    for (const identity of contexts) {
      const ended = await api(identity, '/consultations?status=ended&size=100')
      const saved = ended.items.find(item => item.id === room.id)
      assert.ok(saved?.ended_at, 'Ended consultation must be durably listed with an end time')
      await identity.page.getByRole('radio', { name: 'Ended', exact: true }).check()
      await identity.page.locator('.room').filter({ hasText: message }).waitFor()
      await identity.page.reload()
      await identity.page.getByText('This conversation is read-only.', { exact: true }).waitFor()
      assert.equal(await identity.page.getByRole('radio', { name: 'Ended', exact: true }).isChecked(), true,
        'Reloading an ended room must restore the Ended list')
      await identity.page.locator('.room').filter({ hasText: message }).waitFor()
      await identity.page.locator('.bubble').filter({ hasText: message }).waitFor()
      await identity.page.getByText('Call history (1)', { exact: true }).waitFor()
    }
    console.log('PASS: ended room is listed for both users, survives reload with messages and call history')
    assert.equal(await a.page.locator('.sidebar').getByText('Consultation Records', { exact: true }).count(), 0)
    assert.equal(await a.page.locator('.sidebar').getByText('Consultations', { exact: true }).count(), 1)
    await a.page.getByRole('link', { name: 'Search consultation records', exact: true }).click()
    assert.equal(new URL(a.page.url()).pathname, '/consultations')
    assert.equal(new URL(a.page.url()).searchParams.get('view'), 'records')
    await a.page.getByPlaceholder('Message keyword').fill(message)
    await a.page.getByRole('button', { name: 'Search', exact: true }).click()
    await a.page.getByText('Export includes all 1 matching records.', { exact: false }).waitFor()
    const downloaded = a.page.waitForEvent('download')
    await a.page.getByRole('button', { name: 'Export matching CSV' }).click()
    const download = await downloaded
    const target = path.join(backend, 'runtime', 'm3-browser-export.csv')
    await download.saveAs(target)
    assert.ok(fs.readFileSync(target).subarray(0, 3).equals(Buffer.from([239, 187, 191])))
    assert.match(fs.readFileSync(target, 'utf8'), new RegExp(message))
    await a.page.screenshot({ path: path.join(backend, 'runtime', 'm3-records-browser.png'), fullPage: true })
    assert.deepEqual(errors, [])
    console.log('PASS: hangup metadata, caller history refresh, ended read-only, record filter, BOM CSV, no browser exceptions')
    await a.page.getByRole('button', { name: 'Open record', exact: true }).click()
    await a.page.getByText('This conversation is read-only.', { exact: true }).waitFor()
    assert.equal(new URL(a.page.url()).searchParams.get('room'), String(room.id))
    await a.page.goto(`${base}/consultation-records?room=${room.id}`)
    await a.page.getByPlaceholder('Message keyword').waitFor()
    assert.equal(new URL(a.page.url()).pathname, '/consultations')
    assert.equal(new URL(a.page.url()).searchParams.get('view'), 'records')
    await a.page.getByRole('button', { name: 'Back to conversations', exact: true }).click()
    await a.page.getByText('This conversation is read-only.', { exact: true }).waitFor()
    console.log('PASS: one consultation sidebar entry, embedded records, old-link redirect, record open and return')
    const remoteResponse = a.page.waitForResponse(response => response.url().includes('/api/meetings?') && response.request().method() === 'GET')
    await a.page.getByRole('tab', { name: 'Remote consultation', exact: true }).click()
    assert.equal((await remoteResponse).status(), 200)
    await a.page.getByRole('heading', { name: 'Remote Consultation', exact: true }).waitFor()
    assert.equal(new URL(a.page.url()).searchParams.get('room'), String(room.id))
    await a.page.getByRole('tab', { name: 'Patient consultation', exact: true }).click()
    await a.page.getByText('This conversation is read-only.', { exact: true }).waitFor()
    assert.deepEqual(errors, [])
    console.log('PASS: M3/M5 tab switching loads real meeting API, preserves room query and remounts chat')
    console.log('Manual physical-camera, microphone quality, LAN HTTPS and Excel checks remain required.')
  } finally {
    for (const { context, jwt } of contexts) {
      await context.request.post(`${base}/api/auth/logout`, { headers: { Authorization: `Bearer ${jwt}` } }).catch(() => {})
    }
    await browser.close()
  }
}
main().catch(error => { console.error(error.message.replace(/Bearer [A-Za-z0-9_.-]+/g, 'Bearer [redacted]')); process.exitCode = 1 })
