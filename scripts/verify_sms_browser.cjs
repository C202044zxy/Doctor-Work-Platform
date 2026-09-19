// Optional S1 browser check against scripts/dev.ps1 and real Redis.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const assert = require('node:assert/strict')

async function main() {
  const browser = await chromium.launch({ channel: 'msedge', headless: true })
  const context = await browser.newContext()
  const page = await context.newPage()
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  const base = 'http://127.0.0.1:5173'
  try {
    await page.goto(`${base}/login`)
    await page.getByPlaceholder('Your username').fill('dr_wang')
    await page.getByPlaceholder('Your password').fill(process.env.DEMO_PASSWORD || 'Demo@2026')
    await page.getByRole('button', { name: 'Continue', exact: true }).click()
    await page.getByRole('button', { name: 'SMS (simulated)', exact: true }).click()
    await page.getByPlaceholder('13800138000').fill('13800138000')
    const sent = page.waitForResponse(response => response.url().endsWith('/api/auth/sms/send'))
    await page.getByRole('button', { name: 'Send code', exact: true }).click()
    const sendResponse = await sent
    assert.equal(sendResponse.status(), 200, 'SMS send failed; wait 60 seconds before repeating this check')
    assert.equal((await sendResponse.json()).data.mock, true)
    const previewed = page.waitForResponse(response => response.url().endsWith('/api/auth/sms/preview'))
    await page.getByRole('button', { name: 'View simulated SMS', exact: true }).click()
    const previewResponse = await previewed
    assert.equal(previewResponse.status(), 200)
    const message = (await previewResponse.json()).data
    await page.getByText('Simulated message — nothing was sent.', { exact: false }).waitFor()
    await page.getByPlaceholder('000000').fill(message.code)
    const verified = page.waitForResponse(response => response.url().endsWith('/api/auth/sms/verify'))
    await page.getByRole('button', { name: 'Verify and sign in', exact: true }).click()
    assert.equal((await verified).status(), 200)
    await page.waitForURL('**/dashboard')
    const result = await page.evaluate(async () => {
      const token = localStorage.getItem('dwp.access-token')
      const response = await fetch('/api/me', { headers: { Authorization: `Bearer ${token}` } })
      return { status: response.status, data: (await response.json()).data }
    })
    assert.equal(result.status, 200)
    assert.equal(result.data.username, 'dr_wang')
    assert.deepEqual(errors, [])
    console.log('PASS: password -> simulated SMS -> ticket preview -> JWT -> authenticated dashboard; no browser errors')
  } finally {
    await page.evaluate(async () => {
      const token = localStorage.getItem('dwp.access-token')
      if (token) await fetch('/api/auth/logout', { method: 'POST', headers: { Authorization: `Bearer ${token}` } })
      localStorage.clear()
    }).catch(() => {})
    await browser.close()
  }
}

main().catch(error => { console.error(error.message); process.exitCode = 1 })
