// The tile's still (its cover on the wall, in search engines and sharing):
// a poster, "REMIX PINKASOL !", drawn with the table's own hand-cut shapes
// (duo.html's functions), not the album cover.
//
//   make cover        # dist/pinkasol-tile-cover.png (1200 × 1200)
//
// Opens duo.html (served by serve.py on :8121) in Chromium, stops its
// animation and draws the poster on its canvas. Needs `npm install` (the
// playwright package) and Chromium (npx playwright install chromium).
import { chromium } from 'playwright';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const OUT = join(ROOT, 'dist', 'pinkasol-tile-cover.png');
const S = 1200;
const URL_ = process.env.PLAYGROUND || 'http://localhost:8121/duo.html';

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: S, height: S }, deviceScaleFactor: 1 });
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
await page.goto(URL_);
await page.waitForFunction(() => window.cards && window.cards.length === 10, null, { timeout: 15000 });
await page.addStyleTag({ content: '#back { display: none !important }' });

await page.addScriptTag({ content: `window.poster = function (S) {
  randomSeed(7); noiseSeed(7);
  const u = S / 1200;
  background(BLUE);
  noStroke();
  textFont(FONT);
  textStyle(BOLD);

  // The title, top left, and the cover's star
  fill(PAPER); textAlign(LEFT, BASELINE);
  textSize(190 * u); text('REMIX', 66 * u, 225 * u);
  // the second line as wide as the page allows
  let ts = 190 * u; textSize(ts);
  while (textWidth('PINKASOL !') > S - 140 * u) { ts -= 2 * u; textSize(ts); }
  text('PINKASOL !', 66 * u, 225 * u + ts * 0.95);
  fill(ORANGE); star(700 * u, 150 * u, 64 * u, 11);
  fill(PAPER); textSize(40 * u);
  drawingContext.letterSpacing = \`\${8 * u}px\`;
  text('PICASOL · LA TABLE DU DUO', 72 * u, 225 * u + ts * 0.95 + 72 * u);
  drawingContext.letterSpacing = '0px';

  // The instruments, on a hand-cut table
  fill(PAPER);
  roughRect(40 * u, 805 * u, S - 80 * u, 22 * u, 501, 3 * u);
  roughRect(90 * u, 822 * u, 18 * u, 120 * u, 502, 2 * u);
  roughRect(S - 108 * u, 822 * u, 18 * u, 120 * u, 503, 2 * u);
  INK = PAPER;
  const inst = [['piano', 190, 690, 118], ['drums', 470, 680, 128], ['synth', 760, 715, 112], ['bass', 1030, 680, 118]];
  inst.forEach(([name, x, y, r], i) => { push(); translate(x * u, y * u); drawInstrument(name, r * u, 100 + i * 31); pop(); });

  // Stars around them, as on the table when it plays
  fill(ORANGE);
  [[880, 160, 40], [1040, 300, 26], [800, 470, 30], [1110, 520, 46], [330, 520, 22], [620, 545, 34], [150, 545, 30], [960, 610, 20], [1140, 140, 22]]
    .forEach(([x, y, R], i) => star(x * u, y * u, R * u, 200 + i * 7));

  // Track cards, one being dropped on the piano (a dashed path)
  const card = (id) => window.cards.find((c) => c.id === id);
  noFill(); stroke(PAPER); strokeWeight(4 * u);
  drawingContext.setLineDash([14 * u, 12 * u]);
  bezier(300 * u, 1000 * u, 240 * u, 900 * u, 120 * u, 880 * u, 175 * u, 770 * u);
  drawingContext.setLineDash([]);
  noStroke();
  drawCard(card('09_Cosmos'), 640 * u, 985 * u, 190 * u, 190 * u, 0.12, false);
  drawCard(card('07_Asperges'), 480 * u, 990 * u, 190 * u, 190 * u, -0.06, false);
  drawCard(card('01_Rototo'), 830 * u, 990 * u, 190 * u, 190 * u, 0.2, false);
  drawCard(card('08_Pinkasol'), 255 * u, 960 * u, 200 * u, 200 * u, -0.18, true);
  fill(ORANGE); star(1035 * u, 1110 * u, 48 * u, 300);
};` });

await page.evaluate((S) => {
  // The poster replaces the table's draw(): whatever redraws, draws it
  window.windowResized = () => {};
  window.draw = () => poster(S);
  noLoop();
  pixelDensity(1);
  resizeCanvas(S, S);
  redraw();
}, S);
await page.waitForTimeout(300);

const canvas = await page.$('canvas');
await canvas.screenshot({ path: OUT });
await browser.close();
if (errors.length) { console.error(errors); process.exit(1); }
console.log(`${OUT.replace(ROOT + '/', '')}: ${S} × ${S}`);
