"use strict";
const childProcess = require("node:child_process");
const { chromium } = require("playwright-core");
const css = childProcess.execFileSync("git", ["-C", process.argv[2], "show", process.argv[3] + ":stage-2/ui/theme.css"], { encoding: "utf8" });
async function run() {
  const browser = await chromium.launch({ executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: true });
  try {
    for (const width of [1280, 375]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      await page.route("**/*", route => route.abort());
      await page.setContent("<style>" + css + "</style><button class='button button-secondary button-small' data-testid='logout-button'>Sign out</button>");
      const result = await page.locator("[data-testid=logout-button]").evaluate(element => ({ height: element.getBoundingClientRect().height, coarsePointer: matchMedia("(pointer: coarse)").matches }));
      console.log(JSON.stringify({ revision: process.argv[3], viewport: width, ...result, requiredHeight: 44, isolatedStyleProbe: true }));
      await page.close();
    }
  } finally { await browser.close(); }
}
run().catch(error => { console.error(error); process.exitCode = 1; });
