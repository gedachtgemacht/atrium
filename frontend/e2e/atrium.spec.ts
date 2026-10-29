import { expect, test, type Browser, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'

const seed = () => JSON.parse(readFileSync(new URL('./.seed.json', import.meta.url), 'utf8'))

async function signIn(browser: Browser, first: string): Promise<Page> {
  const page = await (await browser.newContext()).newPage()
  await page.goto('/')
  await page.getByLabel('Email').fill(`${first}@kessler.example`)
  await page.getByLabel('Password').fill(seed().password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Hollmann Bau' })).toBeVisible()
  return page
}

async function asGuest(browser: Browser, who: string): Promise<Page> {
  const page = await (await browser.newContext()).newPage()
  await page.goto(seed().links[who])
  await expect(page.getByRole('heading', { name: 'Kessler Logistik' })).toBeVisible()
  return page
}

test('Lena and Sarah chat live, and the backroom does not exist for Sarah', async ({ browser }) => {
  const lena = await signIn(browser, 'lena')
  const sarah = await asGuest(browser, 'Sarah Hollmann')

  await sarah.getByPlaceholder('Message to Kessler Logistik').fill('Hello from Sarah, live')
  await sarah.keyboard.press('Enter')
  await expect(lena.locator('.feed').getByText('Hello from Sarah, live')).toBeVisible()

  await lena.getByPlaceholder('Message to Hollmann Bau').fill('Hi Sarah, we read you')
  await lena.keyboard.press('Enter')
  await expect(sarah.getByText('Hi Sarah, we read you')).toBeVisible()

  await expect(sarah.getByText(/backroom/i)).toHaveCount(0)
  await expect(sarah.getByText(/agent/i)).toHaveCount(0)
  await expect(sarah.getByText('Only people from Kessler Logistik write here.', { exact: false })).toBeVisible()
})

test('pulling a message into the backroom is invisible to the guest', async ({ browser }) => {
  const lena = await signIn(browser, 'lena')
  const first = lena.locator('.msg', { hasText: 'One more thing' })
  await first.getByRole('button', { name: 'Pull into backroom' }).click()
  await lena.getByPlaceholder('Note for the backroom', { exact: false }).fill('Needs an answer this week')
  await lena.getByRole('button', { name: 'Pull in', exact: true }).click()
  await expect(lena.locator('.backroom .pull-card', { hasText: 'One more thing' })).toBeVisible()
  await expect(lena.locator('.backroom').getByText('Needs an answer this week')).toBeVisible()
  await expect(first.getByText('Pulled into the backroom by you')).toBeVisible()

  const sarah = await asGuest(browser, 'Sarah Hollmann')
  await expect(sarah.getByText('One more thing')).toBeVisible()
  await expect(sarah.getByText(/pulled/i)).toHaveCount(0)
  await expect(sarah.getByText('Needs an answer this week')).toHaveCount(0)
})

test('View as Sarah loads the real guest app, read only', async ({ browser }) => {
  const lena = await signIn(browser, 'lena')
  await lena.locator('#viewas').selectOption({ label: 'Sarah Hollmann' })
  await expect(lena.getByText('This is how Sarah Hollmann sees this channel.')).toBeVisible()
  const frame = lena.frameLocator('iframe[title^="Guest view"]')
  await expect(frame.getByRole('heading', { name: 'Kessler Logistik' })).toBeVisible()
  await expect(frame.getByPlaceholder('Preview, read only')).toBeDisabled()
  await expect(frame.getByText(/backroom/i)).toHaveCount(0)
  await lena.getByRole('button', { name: 'Back to your view' }).click()
  await expect(lena.locator('.backroom')).toBeVisible()
})

test('an invited guest picks a name and joins', async ({ browser }) => {
  const lena = await signIn(browser, 'lena')
  await lena.getByRole('button', { name: 'Invite' }).click()
  await lena.getByRole('button', { name: 'Create link' }).click()
  const link = await lena.locator('#link').inputValue()
  expect(link).toContain('/g/')

  const guest = await (await browser.newContext()).newPage()
  await guest.goto(link.replace('http://localhost:8010', ''))
  await guest.getByLabel('Your name').fill('Petra Lang')
  await guest.getByRole('button', { name: 'Join' }).click()
  await expect(guest.getByRole('heading', { name: 'Kessler Logistik' })).toBeVisible()
  await guest.getByPlaceholder('Message to Kessler Logistik').fill('Petra here')
  await guest.keyboard.press('Enter')
  await expect(lena.locator('.feed').getByText('Petra here')).toBeVisible()
})

test('rooms: joining shows you in the room for everyone, leaving clears it', async ({ browser }) => {
  const lena = await signIn(browser, 'lena')
  const tom = await signIn(browser, 'tom')
  await tom.getByRole('button', { name: /^Warehouse office/ }).click()
  await expect(lena.locator('.room', { hasText: 'Warehouse office' }).getByRole('img', { name: 'Tom Becker' })).toBeVisible()
  await expect(tom.getByText("You're in Warehouse office")).toBeVisible()
  await tom.getByRole('button', { name: 'Leave room' }).click()
  await expect(lena.locator('.room', { hasText: 'Warehouse office' }).getByRole('img', { name: 'Tom Becker' })).toHaveCount(0)
})

test('edits and deletions show up live on the other side', async ({ browser }) => {
  const lena = await signIn(browser, 'lena')
  const sarah = await asGuest(browser, 'Sarah Hollmann')

  await lena.getByPlaceholder('Message to Hollmann Bau').fill('See you on Tusday')
  await lena.keyboard.press('Enter')
  await expect(sarah.getByText('See you on Tusday')).toBeVisible()
  const msg = lena.locator('.feed .msg', { hasText: 'See you on Tusday' })
  await msg.hover()
  await msg.getByRole('button', { name: 'Edit' }).click()
  await lena.getByLabel('Edit message').fill('See you on Tuesday')
  await lena.getByRole('button', { name: 'Save' }).click()
  const seen = sarah.locator('.msg', { hasText: 'See you on Tuesday' })
  await expect(seen).toBeVisible()
  await expect(seen.getByText('edited')).toBeVisible()

  await sarah.getByPlaceholder('Message to Kessler Logistik').fill('Oops, wrong channel')
  await sarah.keyboard.press('Enter')
  await expect(lena.locator('.feed').getByText('Oops, wrong channel')).toBeVisible()
  const mine = sarah.locator('.msg', { hasText: 'Oops, wrong channel' })
  await mine.hover()
  await mine.getByRole('button', { name: 'Delete' }).click()
  await sarah.getByRole('button', { name: 'Really delete?' }).click()
  await expect(lena.locator('.feed').getByText('Oops, wrong channel')).toHaveCount(0)
})

test('an admin adds a site with a room, and colleagues see it right away', async ({ browser }) => {
  const lena = await signIn(browser, 'lena')
  const tom = await signIn(browser, 'tom')
  await lena.goto('/#/admin')
  await lena.getByRole('tab', { name: 'Rooms' }).click()
  await lena.getByRole('button', { name: 'Add floor or site' }).click()
  await lena.locator('.floor-list li').last().locator('input').first().fill('Erfurt depot')
  await lena.getByRole('button', { name: 'Save floors' }).click()
  await expect(lena.getByText('Floors saved')).toBeVisible()
  await lena.getByRole('group', { name: 'Floor to edit' }).getByRole('button', { name: 'Erfurt depot' }).click()
  await lena.getByRole('button', { name: 'New room here' }).first().click()
  await lena.getByLabel('Name', { exact: true }).fill('Depot office')
  await lena.getByLabel('Notes go to').selectOption({ label: '#warehouse' })
  await lena.getByLabel('Only members of that channel can go in').check()
  await lena.getByRole('button', { name: 'Add room' }).click()
  await expect(lena.getByText('Saved', { exact: true })).toBeVisible()

  // Tom sees the new site live; he is in #warehouse, so he may go in.
  await tom.getByRole('group', { name: 'Floors' }).getByRole('button', { name: 'Erfurt depot' }).click()
  await tom.getByRole('button', { name: /^Depot office/ }).click()
  await expect(tom.getByText("You're in Depot office")).toBeVisible()
  // Lena is not in #warehouse: locked for her.
  await lena.goto('/')
  await lena.getByRole('group', { name: 'Floors' }).getByRole('button', { name: 'Erfurt depot' }).click()
  await lena.getByRole('button', { name: /^Depot office/ }).click()
  await expect(lena.getByText('Only members of #warehouse can go in.')).toBeVisible()
})

test('German: the company language switches the UI, guests follow their browser', async ({ browser }) => {
  const lena = await signIn(browser, 'lena')
  const h = { 'X-Requested-With': 'atrium' }
  await lena.request.patch('/api/admin/settings', { data: { language: 'de' }, headers: h })
  try {
    await lena.reload()
    await expect(lena.getByRole('heading', { name: 'Räume' })).toBeVisible()
    await expect(lena.locator('.backroom').getByRole('heading', { name: 'Hinterzimmer' })).toBeVisible()
    await expect(lena.getByRole('button', { name: 'Ins Hinterzimmer holen' }).first()).toBeVisible()
    await expect(lena.getByText('Hier schreiben nur Menschen')).toBeVisible()

    const de = await (await browser.newContext({ locale: 'de-DE' })).newPage()
    await de.goto(seed().links['Jan Petersen'])
    await expect(de.getByText('Hier schreiben nur Menschen von Kessler Logistik.', { exact: false })).toBeVisible()
    const en = await (await browser.newContext({ locale: 'en-GB' })).newPage()
    await en.goto(seed().links['Jan Petersen'])
    await expect(en.getByText('Only people from Kessler Logistik write here.', { exact: false })).toBeVisible()
  } finally {
    await lena.request.patch('/api/admin/settings', { data: { language: 'en' }, headers: h })
  }
})
