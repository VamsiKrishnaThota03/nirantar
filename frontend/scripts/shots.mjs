/**
 * Drives the dashboard in a real browser to capture the screenshots used in
 * the README and the demo video, and to eyeball the interactive views that a
 * static screenshot cannot reach.
 *
 * Usage (with the backend already running on 127.0.0.1:8000):
 *   node scripts/shots.mjs [outputDir]
 *
 * Needs Chrome installed locally; it drives the existing binary rather than
 * downloading one.
 */

import { mkdir } from "node:fs/promises";
import path from "node:path";
import puppeteer from "puppeteer-core";

const BASE = process.env.NIRANTAR_URL ?? "http://127.0.0.1:8000";
const OUT = process.argv[2] ?? "docs/screenshots";

const CHROME_CANDIDATES = [
  process.env.CHROME_PATH,
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/Applications/Chromium.app/Contents/MacOS/Chromium",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
  "/usr/bin/chromium-browser",
].filter(Boolean);

async function findChrome() {
  const { access } = await import("node:fs/promises");
  for (const candidate of CHROME_CANDIDATES) {
    try {
      await access(candidate);
      return candidate;
    } catch {
      /* try the next one */
    }
  }
  throw new Error(
    `Could not find Chrome. Set CHROME_PATH. Tried:\n${CHROME_CANDIDATES.join("\n")}`,
  );
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function main() {
  await mkdir(OUT, { recursive: true });
  const executablePath = await findChrome();
  const browser = await puppeteer.launch({
    executablePath,
    headless: "shell",
    args: ["--hide-scrollbars", "--disable-gpu", "--force-color-profile=srgb"],
  });

  try {
    const page = await browser.newPage();
    // deviceScaleFactor 1 keeps the committed PNGs a sane size for a git
    // repository; these are read on screen, not printed.
    await page.setViewport({ width: 1440, height: 1000, deviceScaleFactor: 1 });

    const shot = async (name) => {
      const file = path.join(OUT, `${name}.png`);
      await page.screenshot({ path: file, fullPage: true });
      console.log(`  → ${file}`);
    };

    const setTheme = async (theme) => {
      await page.evaluate((value) => {
        localStorage.setItem("nirantar-theme", value);
      }, theme);
    };

    console.log("1/8  district view (light)");
    await page.goto(`${BASE}/#district`, { waitUntil: "networkidle2" });
    await setTheme("light");
    await page.reload({ waitUntil: "networkidle2" });
    await sleep(900);
    await shot("01-the-gap-light");

    console.log("2/8  district view (dark)");
    await setTheme("dark");
    await page.reload({ waitUntil: "networkidle2" });
    await sleep(900);
    await shot("02-the-gap-dark");

    console.log("3/8  agent run and resulting plan");
    await setTheme("light");
    await page.goto(`${BASE}/#agents`, { waitUntil: "networkidle2" });
    await sleep(800);
    // Click "Run the agents".
    const clicked = await page.evaluate(() => {
      const button = [...document.querySelectorAll("button")].find((element) =>
        element.textContent?.trim().startsWith("Run the agents"),
      );
      if (!button) return false;
      button.click();
      return true;
    });
    if (!clicked) throw new Error("could not find the 'Run the agents' button");
    // No mid-flight screenshot: with no model key the five agents finish in
    // well under a millisecond, so there is no intermediate state to
    // photograph. That is a property worth stating rather than faking.

    // Wait for the plan to render.
    await page.waitForFunction(
      () => document.body.innerText.includes("Against a conventional referral"),
      { timeout: 45000 },
    );
    await sleep(700);
    await shot("03-agent-plan");

    console.log("4/8  closing with evidence");
    const closed = await page.evaluate(() => {
      const button = [...document.querySelectorAll("button")].find((element) =>
        element.textContent?.includes("Record evidence"),
      );
      if (!button) return false;
      button.click();
      return true;
    });
    if (closed) {
      await sleep(1600);
      await shot("04-closed-with-evidence");
    } else {
      console.log("  (no close button; skipping)");
    }

    console.log("5/8  impact ledger, after planning a batch");
    await page.goto(`${BASE}/#ledger`, { waitUntil: "networkidle2" });
    await sleep(700);
    await page.evaluate(() => {
      const button = [...document.querySelectorAll("button")].find((element) =>
        element.textContent?.includes("Plan 300 obligations"),
      );
      button?.click();
    });
    await page.waitForFunction(
      () => document.body.innerText.includes("Planned "),
      { timeout: 90000 },
    );
    await sleep(1200);
    await shot("05-impact-ledger");

    console.log("6/8  the controlled trial");
    await page.goto(`${BASE}/#trial`, { waitUntil: "networkidle2" });
    await sleep(800);
    await page.evaluate(() => {
      const button = [...document.querySelectorAll("button")].find((element) =>
        element.textContent?.includes("Run the trial"),
      );
      button?.click();
    });
    await page.waitForFunction(
      () => document.body.innerText.includes("Backlog burn-down"),
      { timeout: 120000 },
    );
    await sleep(1200);
    await shot("06-the-trial");

    console.log("7/8  the field app");
    await page.goto(`${BASE}/#field`, { waitUntil: "networkidle2" });
    await page.waitForFunction(
      () => document.body.innerText.includes("Record it done"),
      { timeout: 45000 },
    );
    await sleep(800);
    await shot("07-field-app");

    console.log("8/8  method and sources");
    await page.goto(`${BASE}/#method`, { waitUntil: "networkidle2" });
    await sleep(900);
    await shot("08-method-and-sources");

    // Report anything the page logged, so a console error cannot hide behind
    // a screenshot that happens to look fine.
    console.log("\nDone.");
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
