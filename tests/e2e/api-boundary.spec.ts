import { expect, test } from "../../frontend/test-support/playwright";
import { buildFixture, samples } from "../../frontend/lib/mock/fixtures";

test.skip(
  process.env.NEXT_PUBLIC_MOCK !== "0",
  "Requires the API adapter build; routes are explicit test fixtures",
);

test.beforeEach(async ({ page }) => {
  const createdAt = new Date().toISOString();
  const fixture = buildFixture(
    "benign-csv-tool",
    "contract-upload",
    ["ci"],
    Date.now(),
  );
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/events")) {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: fixture.events
          .map((event) => `data: ${JSON.stringify(event)}\n\n`)
          .join(""),
      });
      return;
    }
    const payload =
      path === "/api/health"
        ? {
            ok: true,
            mode: "live",
            runner: "up",
            inference: "down",
            observer_verified: true,
            version: "test-contract",
            capabilities: { paste: true, zip: true, npm: false, burn: false },
          }
        : path === "/api/samples"
          ? samples
          : path === "/api/jobs"
            ? { job_id: "contract-upload" }
            : path.endsWith("/report")
              ? { ...fixture.report, mode: "mock" }
              : path.endsWith("/source")
                ? fixture.source
                : {
                    job_id: "contract-upload",
                    mode: "mock",
                    status: "done",
                    stage: "verdict",
                    verdict: "SAFE_OBSERVED",
                    tier: "standard",
                    created_at: createdAt,
                  };
    await route.fulfill({
      status: path === "/api/jobs" ? 201 : 200,
      json: payload,
    });
  });
});

test("@api-boundary Python upload preserves filename through the form and request", async ({
  page,
}) => {
  await page.goto("/");
  const upload = page.getByRole("tab", { name: "Upload file" });
  await expect(upload).toBeEnabled();
  await upload.click();
  await page.locator("#artifact-file").setInputFiles({
    name: "script.py",
    mimeType: "text/x-python",
    buffer: Buffer.from("print('python')"),
  });
  await expect(page.getByLabel("Original filename")).toHaveValue("script.py");
  await expect(page.getByLabel("Source text")).toHaveValue("print('python')");
  const request = page.waitForRequest(
    (request) =>
      request.method() === "POST" && request.url().endsWith("/api/jobs"),
  );
  await page.getByRole("button", { name: "Analyze artifact" }).click();
  expect((await request).postDataJSON()).toMatchObject({
    input_type: "paste",
    filename: "script.py",
    content: "print('python')",
  });
  await expect(page).toHaveURL(/jobs\/contract-upload/);
  await expect(
    page.getByText(/MOCK: synthetic frontend\/backend fixtures/),
  ).toBeVisible();
});

test("@api-boundary ZIP upload sends original archive bytes instead of paste", async ({
  page,
}) => {
  const archive = Buffer.from(
    "UEsDBBQAAAAAAAAAIVyEBqm3DAAAAAwAAAAHAAAAbWFpbi5weXByaW50KCd6aXAnKVBLAQIUAxQAAAAAAAAAIVyEBqm3DAAAAAwAAAAHAAAAAAAAAAAAAACAAQAAAABtYWluLnB5UEsFBgAAAAABAAEANQAAADEAAAAAAA==",
    "base64",
  );
  await page.goto("/");
  await expect(page.getByRole("tab", { name: "Upload file" })).toBeEnabled();
  await page.getByRole("tab", { name: "Upload file" }).click();
  await page.locator("#artifact-file").setInputFiles({
    name: "project.zip",
    mimeType: "application/zip",
    buffer: archive,
  });
  await expect(page.getByText("Selected archive: project.zip")).toBeVisible();
  const request = page.waitForRequest(
    (request) =>
      request.method() === "POST" && request.url().endsWith("/api/jobs"),
  );
  await page.getByRole("button", { name: "Analyze artifact" }).click();
  expect((await request).postDataJSON()).toMatchObject({
    input_type: "zip",
    filename: "project.zip",
    content: archive.toString("base64"),
  });
});
