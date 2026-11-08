import { expect, test } from "../../frontend/test-support/playwright";
import { samples } from "../../frontend/lib/mock/fixtures";

const scenarios = samples.map((sample) => ({
  ...sample,
  verdict: sample.expected_verdict.replaceAll("_", " "),
  finding: sample.id !== "benign-csv-tool",
  canary: sample.id === "evil-installer",
}));

for (const scenario of scenarios) {
  test(`${scenario.id}: submit → events → expected report → evidence`, async ({
    page,
  }, testInfo) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto("/");
    await expect(
      page.getByText("MOCK / SIMULATED", { exact: true }),
    ).toBeVisible();
    if (scenario.canary && testInfo.project.name === "desktop") {
      await page.screenshot({
        path: testInfo.outputPath("submit-mock.png"),
        fullPage: true,
      });
    }
    await page.getByRole("radio", { name: new RegExp(scenario.title) }).check();
    await page.getByRole("button", { name: "Run simulation" }).click();
    await expect(page).toHaveURL(new RegExp(`/jobs/mock-${scenario.id}`));
    await expect(page.getByTestId("event-row").first()).toBeVisible();
    await expect(page.getByText(scenario.verdict, { exact: true })).toBeVisible(
      { timeout: 15000 },
    );
    await expect(
      page.getByRole("heading", { name: "Limitations", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText(/No submitted code was executed/),
    ).toBeVisible();
    if (scenario.canary) {
      await expect(page.getByRole("main").getByRole("alert")).toContainText(
        "SIMULATED CANARY ALERT",
      );
      await page.emulateMedia({ reducedMotion: "reduce" });
      expect(
        await page
          .locator(".canary-triggered")
          .evaluate((element) => getComputedStyle(element).animationName),
      ).toBe("none");
    } else
      await expect(
        page.getByText("SIMULATED CANARY ALERT", { exact: true }),
      ).toHaveCount(0);
    if (scenario.finding) {
      await expect(
        page.getByText("Blocked", { exact: true }).first(),
      ).toBeVisible();
      await page.getByRole("button", { name: "Pause autoscroll" }).click();
      await expect(
        page.getByRole("button", { name: "Resume autoscroll" }),
      ).toHaveAttribute("aria-pressed", "true");
      await page
        .getByRole("combobox", { name: "Severity" })
        .selectOption("warn");
      await page.getByRole("button", { name: /evidence events/ }).click();
      await expect(
        page.getByRole("combobox", { name: "Severity" }),
      ).toHaveValue("all");
      await expect(page.getByTestId("highlighted-source-line")).toHaveCount(2);
      await expect(
        page
          .getByRole("status")
          .filter({ hasText: "All referenced events are available" }),
      ).toBeVisible();
      await expect(page.locator(".evidence-selected").first()).toBeVisible();
      if (scenario.canary) {
        await page.evaluate(() => window.scrollTo(0, 0));
        await page.screenshot({
          path: testInfo.outputPath(`report-mock-${testInfo.project.name}.png`),
          fullPage: true,
        });
      }
    } else
      await expect(page.getByText("Blocked", { exact: true })).toHaveCount(0);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    expect(errors).toEqual([]);
  });
}

test("unknown jobs surface errors and allow retry", async ({ page }) => {
  await page.goto("/jobs/missing-job");
  await expect(page.getByRole("alert").first()).toContainText("not_found");
  await page
    .getByRole("button", { name: "Retry", exact: true })
    .first()
    .click();
  await expect(page.getByRole("alert").first()).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Claim vs. behavior" }),
  ).toHaveCount(0);
});

test("keyboard selection, validation, and truthful unavailable inputs", async ({
  page,
}) => {
  await page.goto("/");
  const profile = page.getByRole("checkbox", { name: /Developer laptop/ });
  await profile.focus();
  await page.keyboard.press("Space");
  await expect(profile).not.toBeChecked();
  await page.getByRole("checkbox", { name: /CI runner/ }).uncheck();
  await page.getByRole("button", { name: "Run simulation" }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "at least one environment",
  );
  await page.getByRole("tab", { name: "Team samples" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: "Paste source" })).toBeFocused();
  await expect(
    page.getByText(/Source submission is unavailable in simulation/),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Run simulation" }),
  ).toBeDisabled();
  await page.emulateMedia({ reducedMotion: "reduce" });
  expect(
    await page
      .locator("body")
      .evaluate(() => matchMedia("(prefers-reduced-motion: reduce)").matches),
  ).toBe(true);
});
