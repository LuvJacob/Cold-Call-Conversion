import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Calling workspace." }),
  ).toBeVisible();
});

test("prospect entry, preparation, active-call recovery, outcome and deletion", async ({
  page,
}) => {
  await page.getByRole("button", { name: "Add prospect", exact: true }).click();
  await page.getByLabel("Full name").fill("Jamie Test");
  await page.getByLabel("Company", { exact: true }).fill("Example Systems");
  await page.getByLabel("Job title").fill("IT Director");
  await page
    .getByLabel("Your notes")
    .fill("Keep these notes exactly.\nAsk about recovery.");
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Add prospect", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Jamie Test", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Prepare sample brief", exact: true })
    .click();
  await expect(
    page.getByText("No live company research has been performed.", {
      exact: false,
    }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Sources" }).click();
  await expect(
    page.getByRole("heading", { name: "No research sources yet" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Call connected", exact: true })
    .click();
  await expect(
    page.getByText("IN CONVERSATION", { exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Jamie Test", exact: true }),
  ).toBeVisible();
  await page.getByLabel("Call outcome").selectOption("follow-up");
  await page.getByRole("button", { name: "End call", exact: true }).click();
  await page
    .getByRole("button", { name: "View Jamie Test", exact: true })
    .click();
  await expect(page.getByText("Follow-up", { exact: true })).toBeVisible();
  await page
    .getByRole("button", { name: "Remove Jamie Test", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Remove prospect", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "View Jamie Test", exact: true }),
  ).toHaveCount(0);
});

test("CSV previews valid rows and skips duplicate and invalid records", async ({
  page,
}) => {
  await page.getByRole("button", { name: "Import CSV" }).click();
  await page.getByLabel("CSV file").setInputFiles({
    name: "prospects.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(
      'name,company,role,notes\n"Casey, Jr.",Example,CTO,"Line one\nLine two"\n"Casey, Jr.",Example,CTO,Duplicate\n,Example,CTO,Invalid',
    ),
  });
  await expect(page.getByText("1 duplicate skipped")).toBeVisible();
  await expect(
    page.getByText("Rows with errors will not be imported."),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Import 1 valid prospect", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "View Casey, Jr.", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Line one\nLine two", { exact: true }),
  ).toBeVisible();
});

test("lists, filters, editing, sources, and failed preparation recovery", async ({
  page,
}) => {
  await page.getByRole("tab", { name: "Sources" }).click();
  await expect(
    page.getByRole("heading", { name: "Company overview", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "View Priya Shah", exact: true })
    .click();
  await expect(page.getByText("Preparation needs another try")).toBeVisible();
  await page
    .getByRole("button", { name: "Retry demo research", exact: false })
    .click();
  await expect(
    page.getByText("No live company research has been performed.", {
      exact: false,
    }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Create calling list", exact: true })
    .click();
  await page.getByLabel("List name").fill("New campaign");
  await page.getByRole("button", { name: "Create list", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Your next conversation starts here" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "October outreach", exact: false })
    .click();
  await page.getByLabel("Search prospects").fill("maya");
  await expect(
    page.getByRole("button", { name: "View Jordan Ellis", exact: true }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "Edit Maya Chen", exact: true })
    .click();
  await page.getByLabel("Company", { exact: true }).fill("Updated Company");
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(
    page.getByText("A little research goes a long way."),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByText("Updated Company", { exact: true }).first(),
  ).toBeVisible();
});

test("small screen navigation, briefing, and dialog focus", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page
    .getByRole("button", { name: "View Maya Chen", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Maya Chen", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Maya Chen", exact: true }),
  ).toBeFocused();
  await page
    .getByRole("button", { name: "Back to calling list", exact: false })
    .click();
  await expect(
    page.getByRole("button", { name: "View Maya Chen", exact: true }),
  ).toBeFocused();
  await page
    .getByRole("button", { name: "Open navigation", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Open navigation", exact: true }),
  ).toBeFocused();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > innerWidth,
  );
  expect(overflow).toBe(false);
});

test("another tab cannot overwrite a newer saved workspace", async ({
  page,
}) => {
  const other = await page.context().newPage();
  await other.goto("/");
  await expect(
    other.getByRole("heading", { name: "Calling workspace." }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Create calling list", exact: true })
    .click();
  await page.getByLabel("List name").fill("Keep this list");
  await page.getByRole("button", { name: "Create list", exact: true }).click();
  await expect(
    other.getByText("This workspace changed in another tab.", { exact: false }),
  ).toBeVisible();
  await other
    .getByRole("button", { name: "View Jordan Ellis", exact: true })
    .click();
  await other
    .getByRole("button", { name: "Edit Jordan Ellis", exact: true })
    .click();
  await other.getByLabel("Company", { exact: true }).fill("Stale tab edit");
  await other
    .getByRole("button", { name: "Save changes", exact: true })
    .click();
  const persisted = await other.evaluate(() =>
    JSON.parse(localStorage.getItem("cold-call-conversion:workspace:v1")!),
  );
  expect(
    persisted.lists.some((l: { name: string }) => l.name === "Keep this list"),
  ).toBe(true);
  expect(
    persisted.prospects.some(
      (p: { company: string }) => p.company === "Stale tab edit",
    ),
  ).toBe(false);
  await other.close();
});

test("storage corruption is surfaced without overwriting the recovery data", async ({
  page,
}) => {
  await page.evaluate(() =>
    localStorage.setItem(
      "cold-call-conversion:workspace:v1",
      "{invalid saved data",
    ),
  );
  await page.reload();
  await expect(
    page.getByText("Saved data could not be read.", { exact: false }),
  ).toBeVisible();
  expect(
    await page.evaluate(() =>
      localStorage.getItem("cold-call-conversion:workspace:v1"),
    ),
  ).toBe("{invalid saved data");
});

test("layout captures and no page errors", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.screenshot({
    path: "test-results/workspace-desktop.png",
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Call connected", exact: true })
    .click();
  await page.screenshot({
    path: "test-results/on-call-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 320, height: 720 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
  ).toBe(false);
  await page.screenshot({
    path: "test-results/on-call-mobile.png",
    fullPage: true,
  });
  expect(errors).toEqual([]);
});

test("workspace and on-call accessibility", async ({ page }) => {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  expect(
    results.violations.map((v) => ({
      id: v.id,
      nodes: v.nodes.map((n) => ({
        target: n.target,
        summary: n.failureSummary,
      })),
    })),
  ).toEqual([]);
  await page
    .getByRole("button", { name: "Call connected", exact: true })
    .click();
  const onCall = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  expect(
    onCall.violations.map((v) => ({
      id: v.id,
      nodes: v.nodes.map((n) => ({
        target: n.target,
        summary: n.failureSummary,
      })),
    })),
  ).toEqual([]);
});

test("contacts and briefing scroll independently while call controls stay visible", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.evaluate(() => {
    const key = "cold-call-conversion:workspace:v1";
    const saved = JSON.parse(localStorage.getItem(key)!);
    const template = saved.prospects[0];
    for (let i = 0; i < 35; i++)
      saved.prospects.push({
        ...template,
        id: `scroll-${i}`,
        name: `Scroll Contact ${i}`,
      });
    localStorage.setItem(key, JSON.stringify(saved));
  });
  await page.reload();
  const call = page.getByRole("button", {
    name: "Call connected",
    exact: true,
  });
  await expect(call).toBeInViewport();
  const initial = await call.boundingBox();
  const contacts = page.getByRole("region", { name: "Contacts", exact: true });
  await contacts.evaluate((el) => {
    el.scrollTop = el.scrollHeight;
  });
  expect(await contacts.evaluate((el) => el.scrollTop)).toBeGreaterThan(0);
  await expect(
    page.getByRole("button", { name: "View Scroll Contact 34", exact: true }),
  ).toBeInViewport();
  const brief = page.getByRole("tabpanel");
  await brief.evaluate((el) => {
    el.scrollTop = el.scrollHeight;
  });
  expect(await brief.evaluate((el) => el.scrollTop)).toBeGreaterThan(0);
  expect(await call.boundingBox()).toEqual(initial);
  expect(
    await page.evaluate(() => ({
      x: window.scrollX,
      y: window.scrollY,
      overflow: document.documentElement.scrollHeight > innerHeight,
    })),
  ).toEqual({ x: 0, y: 0, overflow: false });
  await page.screenshot({ path: "test-results/fixed-workspace-desktop.png" });
  await page.setViewportSize({ width: 1280, height: 720 });
  await expect(call).toBeInViewport();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollHeight > innerHeight,
    ),
  ).toBe(false);
  await page.screenshot({ path: "test-results/fixed-workspace-laptop.png" });
  await page
    .getByRole("button", { name: "Next prospect", exact: true })
    .click();
  await expect(page.getByRole("tabpanel")).toHaveJSProperty("scrollTop", 0);
  await call.click();
  await expect(
    page.getByRole("button", { name: "End call", exact: true }),
  ).toBeInViewport();
});

test("mobile keeps the briefing header and call controls above an internal scroller", async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 720 });
  await page
    .getByRole("button", { name: "View Maya Chen", exact: true })
    .click();
  const call = page.getByRole("button", {
    name: "Call connected",
    exact: true,
  });
  await expect(call).toBeInViewport();
  await page.getByRole("tabpanel").evaluate((el) => {
    el.scrollTop = el.scrollHeight;
  });
  await expect(call).toBeInViewport();
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollHeight > innerHeight ||
        document.documentElement.scrollWidth > innerWidth,
    ),
  ).toBe(false);
  await page.screenshot({ path: "test-results/fixed-workspace-mobile.png" });
  await call.click();
  await expect(
    page.getByRole("button", { name: "End call", exact: true }),
  ).toBeInViewport();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollHeight > innerHeight,
    ),
  ).toBe(false);
});
