import { expect, test } from '@playwright/test'

async function expectNoHorizontalOverflow(page: import('@playwright/test').Page) {
  const dimensions = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    pageWidth: document.documentElement.scrollWidth,
  }))
  expect(dimensions.pageWidth).toBeLessThanOrEqual(dimensions.viewport)
}

test('loads synthetic defaults and scores a transaction', async ({ page }) => {
  await page.goto('/')

  await expect(page.getByText('API connected')).toBeVisible()
  await expect(page.getByRole('spinbutton', { name: 'Transaction amount' })).toHaveValue('75')
  await expect(page.getByRole('spinbutton', { name: 'Client ID' })).toHaveValue('1')
  await expect(page.getByRole('spinbutton', { name: 'Card ID' })).toHaveValue('10')
  await expect(page.getByRole('spinbutton', { name: 'Merchant ID' })).toHaveValue('20')

  await page.getByRole('button', { name: 'Run assessment' }).click()
  await expect(page.getByText('BINARY PREDICTION')).toBeVisible()
  await expect(page.getByText('Native model output')).toBeVisible()

  await page.getByRole('button', { name: 'History signals' }).click()
  await expect(page.getByRole('heading', { name: 'History signals' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Card behavior' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Merchant profile' })).toBeVisible()

  await page.getByRole('button', { name: 'Request timing' }).click()
  await expect(page.getByText('Time spent in each part of this request')).toBeVisible()

  await expectNoHorizontalOverflow(page)
})

test('keeps the workbench usable on a mobile viewport', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')

  await expect(page.getByText('Transaction assessment')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Run assessment' })).toBeEnabled()

  await page.getByRole('button', { name: '250' }).click()
  await expect(page.getByRole('spinbutton', { name: 'Transaction amount' })).toHaveValue('250')

  await expectNoHorizontalOverflow(page)
})
