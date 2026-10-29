// README pictures. Start tools/screenshots/stage.py first, then from frontend/: node scripts/screenshots.mjs
import { chromium } from '@playwright/test'
import { readFileSync, mkdirSync, renameSync, readdirSync, rmSync, statSync } from 'node:fs'

const BASE = 'http://localhost:8030'
const stage = JSON.parse(readFileSync('/tmp/atrium-shots/stage.json', 'utf8'))
const L = stage.language
const OUT = new URL(`../../docs/images/${L === 'de' ? 'de/' : ''}`, import.meta.url).pathname
mkdirSync(OUT, { recursive: true })
const T = {
  en: { pull: 'Pull into backroom', pullIn: 'Pull in', note: '@QuoteAgent can you work out the payment terms?', reply: 'Draft a reply in the customer channel',
        move: 'Move to customer channel', send: 'Send', memory: 'Memory', work: 'Work', ask: 'What does Sarah want?', backroom: 'Backroom', rooms: 'Rooms',
        question: 'One more thing', menu: 'Open rooms and channels' },
  de: { pull: 'Ins Hinterzimmer holen', pullIn: 'Reinholen', note: '@QuoteAgent rechnest du das Zahlungsziel durch?', reply: 'Antwort im Kundenkanal entwerfen',
        move: 'In den Kundenkanal übernehmen', send: 'Senden', memory: 'Gedächtnis', work: 'Arbeit', ask: 'Was will Sarah?', backroom: 'Hinterzimmer', rooms: 'Räume',
        question: 'Noch was', menu: 'Räume und Kanäle öffnen' },
}[L]
const locale = L === 'de' ? 'de-DE' : 'en-GB'
// Show the scene at about 10:45 in the morning, whatever time it is now.
const now = new Date()
let offset = Math.round(10.75 - (now.getUTCHours() + now.getUTCMinutes() / 60))
if (offset > 14) offset -= 24
if (offset < -12) offset += 24
const timezoneId = offset === 0 ? 'Etc/GMT' : `Etc/GMT${offset > 0 ? '-' : '+'}${Math.abs(offset)}`
for (const d of ['/tmp/atrium-shots/video', '/tmp/atrium-shots/video2']) rmSync(d, { recursive: true, force: true })

const browser = await chromium.launch()

async function lena(opts = {}) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 960 }, deviceScaleFactor: 2, colorScheme: 'light', locale, timezoneId, ...opts })
  await ctx.request.post(`${BASE}/api/auth/login`, { data: { email: 'lena@kessler.example', password: 'atrium-demo' }, headers: { 'X-Requested-With': 'atrium' } })
  const page = await ctx.newPage()
  await page.goto(`${BASE}/#/c/${stage.shared}`)
  await page.locator('.backroom .work').first().waitFor()
  await page.waitForTimeout(600)
  return page
}

async function showCard(page) {
  await page.locator('.backroom .back-body').evaluate((el) => {
    const card = el.querySelector('.work')
    el.scrollTop = Math.max(0, card.offsetTop - 210)
  })
  await page.mouse.move(5, 5)
  await page.waitForTimeout(300)
}

// 1. Main view, light and dark
let page = await lena()
await showCard(page)
await page.screenshot({ path: OUT + 'main.png' })
await page.context().close()
page = await lena({ colorScheme: 'dark' })
await showCard(page)
await page.screenshot({ path: OUT + 'main-dark.png' })
await page.context().close()

// 2. Phone: channel and backroom drawer
page = await lena({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true })
await page.screenshot({ path: OUT + 'phone-channel.png' })
await page.getByRole('button', { name: T.backroom, exact: true }).click()
await page.waitForTimeout(400)
await page.locator('.backroom .back-body').evaluate((el) => (el.scrollTop = el.querySelector('.work').offsetTop - 60))
await page.screenshot({ path: OUT + 'phone-backroom.png' })
await page.context().close()

// 3. The payment terms flow as a short video: pull in, agent result, draft, send.
const vctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, colorScheme: 'light', locale, timezoneId, recordVideo: { dir: '/tmp/atrium-shots/video', size: { width: 1280, height: 800 } } })
await vctx.request.post(`${BASE}/api/auth/login`, { data: { email: 'lena@kessler.example', password: 'atrium-demo' }, headers: { 'X-Requested-With': 'atrium' } })
page = await vctx.newPage()
await page.goto(`${BASE}/#/c/${stage.shared}`)
await page.locator('.backroom .work').first().waitFor()
await page.waitForTimeout(1200)
const q = page.locator('.feed .msg', { hasText: T.question })
await q.getByRole('button', { name: T.pull }).click()
await page.waitForTimeout(500)
await page.getByPlaceholder(/QuoteAgent/).pressSequentially(T.note, { delay: 35 })
await page.waitForTimeout(400)
await page.getByRole('button', { name: T.pullIn, exact: true }).click()
await page.locator('.backroom .work').nth(1).waitFor()
await page.waitForTimeout(400)
await page.locator('.backroom .back-body').evaluate((el) => el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' }))
await page.waitForTimeout(2500)
await page.getByRole('button', { name: T.reply }).click()
await page.waitForTimeout(2200)
await page.getByRole('button', { name: T.send, exact: true }).first().click()
await page.waitForTimeout(2200)
const sarah = await (await browser.newContext({ viewport: { width: 1280, height: 800 }, colorScheme: 'light', locale, timezoneId, recordVideo: { dir: '/tmp/atrium-shots/video2', size: { width: 1280, height: 800 } } })).newPage()
await sarah.goto(stage.links['Sarah Hollmann'].replace('http://localhost:8030', BASE))
await sarah.waitForTimeout(2600)
await vctx.close()
await sarah.context().close()

// 4. Memory and ask the backroom (the payment question is answered by now)
page = await lena()
await page.getByRole('tab', { name: T.memory }).click()
await page.getByRole('button', { name: T.ask, exact: true }).click()
await page.locator('.answer').waitFor()
await page.locator('.back-body.mem').evaluate((el) => (el.scrollTop = el.scrollHeight))
await page.waitForTimeout(400)
await page.screenshot({ path: OUT + 'memory.png' })

// 5. Hand over the quote: text and PDF in Lena's composer
await page.getByRole('tab', { name: T.work }).click()
await page.waitForTimeout(300)
await page.locator('.backroom .back-body').evaluate((el) => (el.scrollTop = el.querySelector('.work').offsetTop - 210))
await page.getByRole('button', { name: T.move }).click()
await page.locator('.composer .attach').waitFor()
await page.waitForTimeout(150)
await page.screenshot({ path: OUT + 'handover.png' })
await page.getByRole('button', { name: T.send, exact: true }).first().click()
await page.waitForTimeout(800)
await page.context().close()

// 6. What the guest gets
const g = await (await browser.newContext({ viewport: { width: 1280, height: 860 }, deviceScaleFactor: 2, colorScheme: 'light', locale, timezoneId })).newPage()
await g.goto(stage.links['Sarah Hollmann'].replace('http://localhost:8030', BASE))
await g.getByText('.pdf', { exact: false }).first().waitFor()
await g.waitForTimeout(400)
await g.screenshot({ path: OUT + 'guest.png' })
await g.context().close()

// 7. Rooms editor with a second site
page = await lena()
const h = { 'X-Requested-With': 'atrium' }
const site = L === 'de' ? ['Büro Dortmund', 'Depot Erfurt', 'Ladezone', 'Depotbüro'] : ['Dortmund office', 'Erfurt depot', 'Loading bay', 'Depot office']
const plan = await (await page.request.put(`${BASE}/api/admin/floors`, { headers: h, data: { floors: [{ id: 'main', name: site[0], columns: 2 }, { name: site[1], columns: 3 }] } })).json()
const erfurt = plan.floors[1].id
const admin = await (await page.request.get(`${BASE}/api/admin/channels`)).json()
const wh = admin.find((c) => c.name === (L === 'de' ? 'lager' : 'warehouse'))
await page.request.post(`${BASE}/api/admin/rooms`, { headers: h, data: { name: site[2], floor_id: erfurt, col: 0, row: 0, col_span: 2, channel_id: wh.id, members_only: true } })
await page.request.post(`${BASE}/api/admin/rooms`, { headers: h, data: { name: site[3], floor_id: erfurt, col: 2, row: 0, col_span: 1 } })
await page.goto(`${BASE}/#/admin`)
await page.getByRole('tab', { name: T.rooms }).click()
await page.locator('.rooms-editor .room').first().waitFor()
await page.locator('.rooms-editor .room').nth(1).click()
await page.waitForTimeout(400)
await page.screenshot({ path: OUT + 'rooms-editor.png' })
await page.context().close()

await browser.close()

// Videos: keep the newest file of each recording
for (const [dir, name] of [['/tmp/atrium-shots/video', 'flow-lena.webm'], ['/tmp/atrium-shots/video2', 'flow-sarah.webm']]) {
  const f = readdirSync(dir).filter((x) => x.endsWith('.webm')).sort((a, b) => statSync(`${dir}/${b}`).size - statSync(`${dir}/${a}`).size)[0]
  renameSync(`${dir}/${f}`, `/tmp/atrium-shots/${name}`)
  rmSync(dir, { recursive: true })
}
console.log('done', OUT)
