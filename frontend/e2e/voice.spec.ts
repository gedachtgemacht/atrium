import { expect, test, type Browser, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'

// Three people talk in one room over the self hosted LiveKit server, with fake microphones.
test.skip(!process.env.E2E_LIVEKIT_URL, 'needs E2E_LIVEKIT_URL pointing to a LiveKit dev server')

const seed = () => JSON.parse(readFileSync(new URL('./.seed.json', import.meta.url), 'utf8'))

async function signIn(browser: Browser, first: string): Promise<Page> {
  const ctx = await browser.newContext({ permissions: ['microphone'] })
  const page = await ctx.newPage()
  await page.goto('/')
  await page.getByLabel('Email').fill(`${first}@kessler.example`)
  await page.getByLabel('Password').fill(seed().password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Rooms' })).toBeVisible()
  return page
}

test('three browsers talk in Dispatch', async ({ browser }) => {
  test.setTimeout(60_000)
  const people = await Promise.all(['tom', 'aylin', 'jonas'].map((p) => signIn(browser, p)))
  for (const page of people) {
    await page.getByRole('button', { name: /^Dispatch/ }).click()
    await expect(page.getByText("You're in Dispatch")).toBeVisible()
  }
  for (const page of people) {
    await expect(page.getByText('Voice connected.')).toBeVisible({ timeout: 15_000 })
    // Each browser plays the two others.
    await expect.poll(() => page.locator('body > audio').count(), { timeout: 15_000 }).toBe(2)
  }
  // Fake microphones produce a tone, so LiveKit reports speakers and the floor plan shows the ring.
  await expect.poll(() => people[0].locator('.room.r-dispatch .av.talking').count(), { timeout: 15_000 }).toBeGreaterThan(0)

  // Mute shows for everyone, leaving disconnects voice.
  await people[0].getByRole('button', { name: 'Mute' }).click()
  await expect(people[1].locator('.room.r-dispatch .av.muted')).toHaveCount(1)
  await people[2].getByRole('button', { name: 'Leave room' }).click()
  await expect.poll(() => people[0].locator('body > audio').count(), { timeout: 15_000 }).toBe(1)
})
