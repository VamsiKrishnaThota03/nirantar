/**
 * Records the submission demo video.
 *
 * Drives a real browser through the beats in docs/DEMO_SCRIPT.md at a pace a
 * human can talk over, and prints a **cue sheet** with the measured timestamp
 * of each beat so a voiceover can be matched to the footage afterwards.
 *
 * Deliberately paced rather than fast: every state change is held long enough
 * to be read, and scrolling is eased rather than jumped so the eye can follow
 * it. A demo recording that moves at machine speed is unusable for narration.
 *
 * Usage (with the app built and the backend running on 127.0.0.1:8000):
 *   node scripts/record-demo.mjs                  # dark theme
 *   node scripts/record-demo.mjs --theme light
 *   node scripts/record-demo.mjs --out ../docs/demo.webm
 *
 * Needs Chrome and ffmpeg locally.
 */

import { access, mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import puppeteer from "puppeteer-core";

const args = process.argv.slice(2);
const argOf = (name, fallback) => {
  const index = args.indexOf(`--${name}`);
  return index >= 0 && args[index + 1] ? args[index + 1] : fallback;
};

const BASE = process.env.NIRANTAR_URL ?? "http://127.0.0.1:8000";
const THEME = argOf("theme", "dark");
const OUT = path.resolve(argOf("out", "../docs/demo.webm"));
// 16:9 so it needs no letterboxing on YouTube or in a slide.
const WIDTH = 1600;
const HEIGHT = 900;

const CHROME_CANDIDATES = [
  process.env.CHROME_PATH,
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/Applications/Chromium.app/Contents/MacOS/Chromium",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
].filter(Boolean);

async function findChrome() {
  for (const candidate of CHROME_CANDIDATES) {
    try {
      await access(candidate);
      return candidate;
    } catch {
      /* next */
    }
  }
  throw new Error(`Could not find Chrome. Set CHROME_PATH.`);
}

// Global pacing. The submission asks for 2-3 minutes, so holds are tuned to
// land around three. Raise it if you want more room to talk.
const PACE = Number(argOf("pace", "1"));
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms * PACE));

async function main() {
  await mkdir(path.dirname(OUT), { recursive: true });
  const executablePath = await findChrome();

  const browser = await puppeteer.launch({
    executablePath,
    // The screencast API needs real headless, not the shell variant.
    headless: true,
    defaultViewport: { width: WIDTH, height: HEIGHT },
    args: [
      "--hide-scrollbars",
      "--force-color-profile=srgb",
      "--font-render-hinting=none",
      `--window-size=${WIDTH},${HEIGHT}`,
    ],
  });

  const page = await browser.newPage();
  await page.setViewport({ width: WIDTH, height: HEIGHT, deviceScaleFactor: 1 });

  // --- helpers available inside the page --------------------------------

  const smoothScroll = async (to, duration = 1400) => {
    await page.evaluate(
      async (target, ms) => {
        const start = window.scrollY;
        const distance = target - start;
        const began = performance.now();
        // Ease-in-out so the motion reads as deliberate rather than mechanical.
        const ease = (t) =>
          t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
        await new Promise((resolve) => {
          const step = (now) => {
            const progress = Math.min(1, (now - began) / ms);
            window.scrollTo(0, start + distance * ease(progress));
            if (progress < 1) requestAnimationFrame(step);
            else resolve();
          };
          requestAnimationFrame(step);
        });
      },
      to,
      duration,
    );
  };

  const scrollToText = async (needle, { duration = 1400, offset = -90 } = {}) => {
    const y = await page.evaluate((text) => {
      const walker = document.createTreeWalker(
        document.body,
        NodeFilter.SHOW_ELEMENT,
      );
      let node = walker.currentNode;
      while (node) {
        if (
          node.children.length === 0 &&
          node.textContent &&
          node.textContent.trim().startsWith(text)
        ) {
          return node.getBoundingClientRect().top + window.scrollY;
        }
        node = walker.nextNode();
      }
      return null;
    }, needle);
    if (y === null) {
      console.warn(`  (could not find "${needle}" to scroll to)`);
      return false;
    }
    await smoothScroll(Math.max(0, y + offset), duration);
    return true;
  };

  const clickByText = async (text) => {
    const clicked = await page.evaluate((needle) => {
      const button = [...document.querySelectorAll("button")].find((element) =>
        element.textContent?.includes(needle),
      );
      if (!button) return false;
      button.click();
      return true;
    }, text);
    if (!clicked) console.warn(`  (no button matching "${text}")`);
    return clicked;
  };

  const goTab = async (hash) => {
    await page.evaluate((h) => {
      window.location.hash = h;
      window.scrollTo(0, 0);
    }, hash);
    await sleep(900);
  };

  // --- set the theme before recording starts ----------------------------

  await page.goto(`${BASE}/#district`, { waitUntil: "networkidle2" });
  await page.evaluate((theme) => {
    localStorage.setItem("nirantar-theme", theme);
  }, THEME);
  await page.reload({ waitUntil: "networkidle2" });
  await page.waitForFunction(
    () => document.body.innerText.includes("India screens superbly"),
    { timeout: 30000 },
  );
  await sleep(1200);

  // --- record -----------------------------------------------------------

  const cues = [];
  const t0 = Date.now();
  const cue = (label, note) => {
    const elapsed = (Date.now() - t0) / 1000;
    const stamp = `${String(Math.floor(elapsed / 60)).padStart(2, "0")}:${String(
      Math.floor(elapsed % 60),
    ).padStart(2, "0")}`;
    cues.push({ stamp, label, note });
    console.log(`  ${stamp}  ${label}`);
  };

  console.log(`Recording ${THEME} theme to ${OUT}\n`);
  const recorder = await page.screencast({ path: OUT });

  // 1. The claim ---------------------------------------------------------
  cue("Hero — the claim", "India screens superbly and follows up terribly");
  await sleep(6000);
  await scrollToText("People owed care right now", { duration: 1600 });
  cue("Headline numbers", "2,727 people owed care — 11% of the block");
  await sleep(6000);

  // 2. Why reminders don't fix it ---------------------------------------
  await scrollToText("India finds the problem", { duration: 1600 });
  cue("The cascade", "found, then lost — 9,411 screened, 1,175 treated");
  await sleep(7000);
  await scrollToText("What a follow-up actually costs", { duration: 1500 });
  cue("The real cost", "₹367 and 22 km — half are predicted not to attend");
  await sleep(7000);
  await scrollToText("The places that need outreach", { duration: 1600 });
  cue("Block schematic", "the two furthest panchayats get no mobile unit");
  await sleep(6000);

  // 3. The agents --------------------------------------------------------
  await goTab("agents");
  cue("Agent view", "worklist ranked by expected harm, not by date");
  await sleep(5000);

  // Pick the confirmed-TB case deliberately. The top of the ranked queue is
  // currently an under-five severe-malnutrition case needing a specialist,
  // which the planner correctly REFUSES to plan (no specialist slot inside
  // the deadline) and escalates instead. That refusal is a good property but
  // a bad opening shot, so the narrated case is chosen explicitly.
  await page.select("select", "tb_confirmed_not_initiated").catch(() => {});
  await page
    .waitForFunction(
      () => document.body.innerText.includes("TB confirmed, treatment not started"),
      { timeout: 20000 },
    )
    .catch(() => console.warn("  (TB filter did not apply)"));
  await sleep(2500);
  cue("The case", "25M, confirmed TB, 75 days past deadline, no phone, Santali");
  await sleep(4000);
  await clickByText("Run the agents");
  cue("Agents running", "five agents, sub-millisecond, no model calls needed");
  // Either a plan renders, or the system declares the obligation
  // unplannable. Both are valid outcomes, so wait for whichever arrives.
  await page
    .waitForFunction(
      () =>
        document.body.innerText.includes("Against a conventional referral") ||
        document.body.innerText.includes("No viable plan exists"),
      { timeout: 60000 },
    )
    .catch(() => console.warn("  (neither a plan nor an escalation rendered)"));
  await sleep(1200);

  // Read the actual figures off the page. A cue sheet quoting numbers the
  // footage does not show is worse than no cue sheet -- the narrator would
  // contradict the screen.
  const actual = await page.evaluate(() => {
    const text = document.body.innerText;
    const money = text.match(/for ₹([\d,]+) instead of ₹([\d,]+)/);
    const show = text.match(/no-show of (\d+)% against (\d+)%/);
    const strategy = document.querySelector(".card h3 + .sub")?.textContent ?? "";
    return {
      cost: money ? `₹${money[1]}` : null,
      conventionalCost: money ? `₹${money[2]}` : null,
      noShow: show ? `${show[1]}%` : null,
      conventionalNoShow: show ? `${show[2]}%` : null,
      strategy: strategy.slice(0, 120),
    };
  });
  if (actual.cost) {
    console.log(
      `  → plan: ${actual.conventionalCost} to ${actual.cost}, ` +
        `no-show ${actual.conventionalNoShow} to ${actual.noShow}`,
    );
  }

  await scrollToText("Agent trace", { duration: 1400 });
  cue("The trace", "Triage, Reality, Supply, Planner, Verifier");
  await sleep(8000);
  await scrollToText("Against a conventional referral", { duration: 1500 });
  cue(
    "The counterfactual",
    actual.cost
      ? `${actual.conventionalCost} → ${actual.cost}, no-show ${actual.conventionalNoShow} → ${actual.noShow}`
      : "cost and no-show, against a conventional referral",
  );
  await sleep(9000);
  await scrollToText("Outreach —", { duration: 1500 });
  cue("Outreach", "no phone in the household, so a person at the door");
  await sleep(7000);
  await scrollToText("What the planner considered", { duration: 1400 });
  cue("The rejections", "what it threw away, and why — van can't start TB tx");
  await sleep(7000);
  await scrollToText("Why this person would not have attended", {
    duration: 1500,
  });
  cue("Barriers", "named, actionable obstacles rather than motivation");
  await sleep(6000);

  // 4. Proven impact -----------------------------------------------------
  await goTab("ledger");
  cue("Impact ledger", "measurement as a feature, not a slide");
  await sleep(4000);
  await clickByText("Plan 300 obligations");
  await page
    .waitForFunction(() => document.body.innerText.includes("Planned "), {
      timeout: 120000,
    })
    .catch(() => console.warn("  (batch did not finish in time)"));
  await sleep(1000);
  cue("300 planned", "3.8s, zero model calls — the answer to 'does it scale'");
  await sleep(7000);
  await smoothScroll(0, 1200);
  cue("Chain verified", "recompute the hashes yourself; red if we'd edited it");
  await sleep(7000);
  await scrollToText("Chain — most recent", { duration: 1600 });
  cue("The chain", "hash-chained, signed, no identifying data");
  await sleep(5000);

  // 5. The trial ---------------------------------------------------------
  await goTab("trial");
  cue("The trial", "ground truth perturbed away from what the planner believes");
  await sleep(8000);
  await page.select("select", "3").catch(() => {});
  await clickByText("Run the trial");
  await page
    .waitForFunction(
      () => document.body.innerText.includes("Backlog burn-down"),
      { timeout: 180000 },
    )
    .catch(() => console.warn("  (trial did not finish in time)"));
  await sleep(1200);
  await scrollToText("Obligations closed, Nirantar", { duration: 1500 });
  const trialHeadline = await page.evaluate(() => {
    const text = document.body.innerText;
    const multiple = text.match(/([\d.]+)×/);
    const cost = text.match(/(\d+)%\s*of what the status quo costs/);
    return {
      multiple: multiple ? multiple[1] : null,
      cost: cost ? cost[1] : null,
    };
  });
  cue(
    "Trial result",
    trialHeadline.multiple
      ? `${trialHeadline.multiple}× more closures at ${trialHeadline.cost}% of the household cost`
      : "more closures, at a fraction of the household cost",
  );
  await sleep(8000);
  await scrollToText("Backlog burn-down", { duration: 1500 });
  cue("Burn-down", "the status-quo line barely moves");
  await sleep(6000);
  await scrollToText("Were our predictions any good", { duration: 1500 });
  cue("Calibration", "we publish how wrong we were");
  await sleep(5000);
  await scrollToText("Who got left behind", { duration: 1600 });
  cue("Equity audit", "distance gap closed; wage gap NOT closed — we say so");
  await sleep(10000);

  // 6. The field app -----------------------------------------------------
  await goTab("field");
  await page
    .waitForFunction(() => document.body.innerText.includes("Record it done"), {
      timeout: 45000,
    })
    .catch(() => console.warn("  (field app did not load in time)"));
  await sleep(1000);
  cue("Field app", "for the ASHA who actually walks to the house");
  await sleep(5000);
  await scrollToText("This list over 2G", { duration: 1300 });
  cue("2G budget", "1.6 KB per household, under 4s for the whole queue");
  await sleep(5000);

  // Genuinely take the browser offline, then record a visit.
  await page.setOfflineMode(true);
  await page.evaluate(() => window.dispatchEvent(new Event("offline")));
  await sleep(1500);
  cue("Network OFF", "now watch — the queue still works");
  await sleep(3000);
  await clickByText("Record it done");
  await sleep(2000);
  cue("Saved on the handset", "queued locally; an app that needs a signal to record a visit doesn't get used");
  await sleep(8000);
  await page.setOfflineMode(false);
  await page.evaluate(() => window.dispatchEvent(new Event("online")));
  await sleep(3000);
  cue("Back online — synced", "flushed to the signed ledger");
  await sleep(5000);

  // 7. Close -------------------------------------------------------------
  await goTab("method");
  cue("Method & sources", "every constant with its provenance");
  await sleep(5000);
  await scrollToText("Limits of this work", { duration: 1600 });
  cue("Limits, stated plainly", "simulated district; modelled, not measured");
  await sleep(8000);
  await goTab("district");
  cue("Close", "Apache-2.0, FHIR-shaped, needs no new data collection");
  await sleep(5000);

  await recorder.stop();
  const total = (Date.now() - t0) / 1000;
  await browser.close();

  // --- cue sheet --------------------------------------------------------
  const sheet =
    `# Voiceover cue sheet — ${path.basename(OUT)}\n\n` +
    `Recorded ${new Date().toISOString()} · ${THEME} theme · ` +
    `${WIDTH}x${HEIGHT} · ${total.toFixed(1)}s\n\n` +
    `Timestamps are where each beat appears on screen. Full wording to read\n` +
    `is in docs/DEMO_SCRIPT.md.\n\n` +
    `| Time | On screen | Say roughly |\n|---|---|---|\n` +
    cues
      .map((item) => `| ${item.stamp} | ${item.label} | ${item.note} |`)
      .join("\n") +
    "\n";
  const sheetPath = OUT.replace(/\.webm$/, "-cues.md");
  await writeFile(sheetPath, sheet);

  console.log(`\nDone. ${total.toFixed(1)}s of footage.`);
  console.log(`  video : ${OUT}`);
  console.log(`  cues  : ${sheetPath}`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
