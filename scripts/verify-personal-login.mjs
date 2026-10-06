// Real localhost login smoke only. No screenshots, traces, recordings, password prints or key writes.
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { resolve } from 'node:path'
import assert from 'node:assert/strict'

let browser
let phase = 'inputs'
try {
  const [webContext, runtimeDirectory, ownerRecord, origin] = process.argv.slice(2)
  assert.match(origin, /^http:\/\/localhost:[0-9]{4,5}$/)
  const require = createRequire(resolve(webContext, 'package.json'))
  const { chromium } = require('playwright')
  const realm = JSON.parse(await readFile(resolve(runtimeDirectory, 'keycloak/realm.json'), 'utf8'))
  const owner = JSON.parse(await readFile(ownerRecord, 'utf8'))
  const maintainer = realm.users.find(user => user.username === 'maintainer')
  const password = maintainer.credentials.find(value => value.type === 'password').value
  phase = 'anonymous-boundary'
  const anonymous = await fetch(origin + '/api/v1/agent/credentials/deepseek')
  assert.equal(anonymous.status, 401)
  assert.match(anonymous.headers.get('cache-control'), /no-store/)
  browser = await chromium.launch({ channel: 'msedge', headless: true })
  let external = 0, model = 0
  async function newPage() {
    const context = await browser.newContext()
    await context.route('**/*', async route => {
      const url = new URL(route.request().url())
      if (url.origin !== origin) { external++; return route.abort() }
      if (url.pathname.includes('/agent/requests')) model++
      await route.continue()
    })
    return context.newPage()
  }
  phase = 'non-owner-login'
  const page = await newPage()
  await page.goto(origin + '/settings/model-credentials')
  await page.getByRole('button', { name: '使用本地身份服务登录' }).click()
  phase = 'non-owner-username'
  await page.locator('#username').fill('maintainer')
  phase = 'non-owner-password'
  await page.locator('#password').fill(password)
  phase = 'non-owner-submit'
  await page.locator('#kc-login').click()
  phase = 'non-owner-callback'
  await page.waitForURL(origin + '/projects', { timeout: 30000 })
  phase = 'non-owner-denial'
  await page.getByRole('link', { name: '模型凭据' }).click()
  await page.getByRole('alert').waitFor()
  assert.equal(await page.getByLabel('新的 DeepSeek API Key').count(), 0)
  const denied = await page.evaluate(async () => {
    const key = Object.keys(sessionStorage).find(key => key.startsWith('oidc.user:'))
    const user = JSON.parse(sessionStorage.getItem(key))
    const response = await fetch('/api/v1/agent/credentials/deepseek', {
      headers: { Authorization: 'Bearer ' + user.access_token }, cache: 'no-store',
    })
    return { status: response.status, cache: response.headers.get('cache-control') }
  })
  assert.equal(denied.status, 403)
  assert.match(denied.cache, /no-store/)
  await page.context().close()
  phase = 'dedicated-first-login'
  const ownerPage = await newPage()
  await ownerPage.goto(origin + '/settings/model-credentials')
  await ownerPage.getByRole('button', { name: '使用本地身份服务登录' }).click()
  await ownerPage.locator('#username').fill('agent-owner')
  await ownerPage.locator('#password').fill(owner.password)
  await ownerPage.locator('#kc-login').click()
  // Leave first password change to the human owner. No action clears this requirement.
  await ownerPage.locator('#password-new').waitFor({ timeout: 30000 })
  await ownerPage.locator('#password-confirm').waitFor()
  assert.equal(external, 0)
  assert.equal(model, 0)
  console.log('Local OIDC: anonymous 401 / maintainer 403 / dedicated first-login password change / zero model requests PASS')
  console.log('Owner first password change and owner write/delete acceptance remain manual; no API Key was used.')
} catch {
  console.error(`Local OIDC smoke failed at ${phase}; sensitive details suppressed.`)
  process.exitCode = 1
} finally {
  await browser?.close()
}
