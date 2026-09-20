// Optional video regression test: isolated headless Edge, synthetic media only.
// Run after scripts/dev.ps1. Uses synthetic media, not a physical camera.
// PLAYWRIGHT_MODULE_PATH may point to an existing Playwright installation.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const { execFileSync } = require('node:child_process')
const path = require('node:path')
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
      await context.addInitScript(() => {
        const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices)
        window.mediaRequests = 0
        window.mediaTracks = []
        window.busyMedia = false
        window.holdMedia = false
        window.mediaDelay = 0
        navigator.mediaDevices.getUserMedia = async constraints => {
          window.mediaRequests++
          if (window.busyMedia) throw new DOMException('Device in use', 'NotReadableError')
          const stream = await original(constraints)
          window.mediaTracks.push(...stream.getTracks())
          if (window.holdMedia) await new Promise(resolve => { window.releaseMedia = resolve })
          if (window.mediaDelay) await new Promise(resolve => setTimeout(resolve, window.mediaDelay))
          return stream
        }
      })
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
    await Promise.all(contexts.map(({ page }) => page.getByText('active · Connected', { exact: true }).waitFor({ timeout: 60000 })))
    const mode = (identity, value) => identity.page.getByLabel('Local media', { exact: true }).selectOption(value)
    const start = identity => identity.page.getByRole('button', { name: 'Start video call', exact: true }).click()
    const answer = identity => identity.page.getByRole('button', { name: 'Answer', exact: true }).click()
    const connected = () => Promise.all(contexts.map(({ page }) => page.getByText('Video: connected', { exact: true }).waitFor({ timeout: 45000 })))
    const received = identity => identity.page.waitForFunction(() => {
      const video = document.querySelectorAll('.video-call video')[1]
      return video?.videoWidth > 0 && video.srcObject?.getAudioTracks().length > 0
    })
    const idle = () => Promise.all(contexts.map(({ page }) => page.getByRole('button', { name: 'Start video call', exact: true }).waitFor()))
    const hangup = async identity => {
      await identity.page.getByRole('button', { name: 'Hang up', exact: true }).click()
      await idle()
      for (const { page } of contexts) await page.waitForFunction(() => window.mediaTracks.every(track => track.readyState === 'ended'))
    }
    // Model hardware contention, then recover using the new receive-only option.
    await b.page.evaluate(() => { window.busyMedia = true })
    await start(a)
    await answer(b)
    await b.page.getByText('The camera or microphone could not be opened;', { exact: false }).waitFor()
    await idle()
    const bRequests = await b.page.evaluate(() => window.mediaRequests)
    await mode(b, 'receive')
    await start(a)
    await answer(b)
    await connected()
    await received(b)
    assert.equal(await b.page.evaluate(() => window.mediaRequests), bRequests)
    await hangup(a)
    console.log('PASS: device-in-use error is actionable; receive-only callee receives real WebRTC without requesting devices; hangup releases tracks')

    await b.page.evaluate(() => { window.busyMedia = false })
    await mode(a, 'receive')
    await mode(b, 'camera')
    const aRequests = await a.page.evaluate(() => window.mediaRequests)
    await start(a)
    await answer(b)
    await connected()
    await received(a)
    assert.equal(await a.page.evaluate(() => window.mediaRequests), aRequests)
    await hangup(b)
    console.log('PASS: receive-only caller receives camera/audio from callee; no local capture')

    // A 30-second permission delay used to exceed the shared 25-second deadline.
    await mode(a, 'camera')
    await b.page.evaluate(() => { window.mediaDelay = 30000 })
    await start(a)
    await answer(b)
    await connected()
    await Promise.all(contexts.map(received))
    await hangup(a)
    console.log('PASS: delayed media permission beyond the old 25-second timeout still connects bidirectionally')

    await a.page.evaluate(() => { window.holdMedia = true })
    await start(a)
    await a.page.waitForFunction(() => typeof window.releaseMedia === 'function')
    await a.page.getByRole('button', { name: 'Hang up', exact: true }).click()
    await a.page.evaluate(() => window.releaseMedia())
    await a.page.waitForFunction(() => window.mediaTracks.every(track => track.readyState === 'ended'))
    assert.deepEqual(errors, [])
    console.log('PASS: cancellation during pending capture releases late-arriving tracks; no browser exceptions')
    await api(a, `/consultations/${room.id}/end`, {})
  } catch (error) {
    for (const { page } of contexts) {
      console.error('Test page state:', (await page.locator('body').innerText().catch(() => 'unavailable')).slice(-2400))
    }
    throw error
  } finally {
    for (const { context, jwt } of contexts) {
      await context.request.post(`${base}/api/auth/logout`, { headers: { Authorization: `Bearer ${jwt}` } }).catch(() => {})
    }
    await browser.close()
  }
}
main().catch(error => { console.error(error.message.replace(/Bearer [A-Za-z0-9_.-]+/g, 'Bearer [redacted]')); process.exitCode = 1 })
