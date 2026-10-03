"use strict";
const { chromium } = require("playwright-core");
const launch = chromium.launch.bind(chromium);
const browsers = new Set();
chromium.launch = async options => {
  const browser = await launch(options);
  browsers.add(browser);
  browser.on("disconnected", () => browsers.delete(browser));
  return browser;
};
let stopping = false;
async function stop() {
  if (stopping) return;
  stopping = true;
  await Promise.allSettled(Array.from(browsers, browser => browser.close()));
  process.exit(143);
}
process.on("SIGTERM", stop);
process.on("SIGINT", stop);
