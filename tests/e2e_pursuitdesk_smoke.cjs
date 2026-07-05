const assert = require("node:assert/strict");
const { chromium } = require("playwright");

const targetUrl = process.env.PURSUITDESK_E2E_URL || "http://127.0.0.1:4173/index.html?qa=e2e";

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 850 } });
  const messages = [];
  page.on("console", (message) => {
    if (["error", "warning"].includes(message.type())) {
      messages.push(`${message.type()}: ${message.text()}`);
    }
  });

  await page.goto(targetUrl, { waitUntil: "domcontentloaded", timeout: 45000 });
  await page.waitForSelector("#advisor-workflow .workflow-step-chip", { timeout: 30000 });
  await page.waitForSelector(".opp, .empty", { timeout: 30000 });

  assert.match(await page.title(), /PursuitDesk/);
  assert.equal(await page.locator(".filter-panel").evaluate((element) => element.open), true);
  assert.match(await page.locator("#advisor-workflow").innerText(), /CLIENT/);
  assert.match(await page.locator("#proposal-job-status").innerText(), /proposal draft/i);

  await page.locator("#search").fill("zzzzzz-no-match-qa");
  await page.locator("#search").press("Enter");
  await page.waitForSelector("[data-clear-filters]", { timeout: 30000 });
  assert.match(await page.locator("#opportunities").innerText(), /No matching opportunities/);

  await page.locator("[data-clear-filters]").click();
  await page.waitForSelector(".opp", { timeout: 30000 });
  await page.locator(".opp").first().click();
  await page.waitForFunction(() => {
    const title = document.querySelector("#analysis-title")?.textContent || "";
    return title.trim() && !/Select an opportunity/i.test(title);
  }, null, { timeout: 30000 });

  assert.match(await page.locator("#next-action-title").innerText(), /Validate evidence|Draft|Watch|Confirm|Move/i);
  assert.deepEqual(messages, []);
  await browser.close();
})().catch(async (error) => {
  console.error(error);
  process.exit(1);
});
