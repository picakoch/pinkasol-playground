// Uploads the tile's part files (audio/pieces/<track>/p<k>-<inst>.mp3, the
// ones audio/pieces/manifest.json's parts name) to a Tilefolio site's media
// library, as the site's owner, and writes audio/media-urls.json: each
// file's address in the library, which `make tile` puts in the tile.
//
//   OWNER_PASSWORD=… node tools/upload.mjs --email <owner's e-mail> [options]
//   make upload EMAIL=<owner's e-mail>
//
//   --api URL     the instance's admin host (default https://admin.tilefolio.com)
//   --email E     the site's owner (picasol.fr's), as in the admin panel
//   --dry-run     lists what would be uploaded, sends nothing
//   --check       then checks every address: 200, audio/mpeg, and
//                 Access-Control-Allow-Origin * (the tile fetches them from
//                 the box, which has no origin)
//
// The password: OWNER_PASSWORD, else asked (not shown, never written).
// Same route as Tilefolio's own importer (scripts/import-site-files.mjs):
// POST /admin/login, then POST /upload as the owner, so the files land in
// that owner's site library, on the media CDN. Each file is uploaded as
// "pinkasol-tile_<track>_<file>.mp3"; one already in the library under that
// name is reused, so a second run only uploads what's missing (and an
// interrupted one resumes). media-urls.json is written as it goes.
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const PIECES = join(ROOT, 'audio', 'pieces');
const URLS = join(ROOT, 'audio', 'media-urls.json');
const PREFIX = 'pinkasol-tile_';
const PARALLEL = 4;

const args = process.argv.slice(2);
const option = (name) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : undefined; };
const flag = (name) => args.includes(name);
const API = (option('--api') || 'https://admin.tilefolio.com').replace(/\/+$/, '');
const EMAIL = option('--email');
const DRY = flag('--dry-run');
const CHECK = flag('--check');

// The library's name of a part file: "01_Rototo/p1-drums.mp3" ->
// "pinkasol-tile_01_Rototo_p1-drums.mp3"
const libraryName = (file) => PREFIX + file.replace('/', '_');

function partFiles() {
  const manifest = JSON.parse(readFileSync(join(PIECES, 'manifest.json'), 'utf8'));
  return [...new Set(manifest.tracks.flatMap((t) => t.parts.flatMap((p) => Object.values(p.files))))].sort();
}

async function call(method, path, { body, auth, form } = {}) {
  const headers = { accept: 'application/json', ...(auth ? { authorization: `Bearer ${auth}` } : {}) };
  if (body !== undefined) headers['content-type'] = 'application/json';
  for (let attempt = 1; ; attempt++) {
    let response;
    try {
      response = await fetch(`${API}${path}`, { method, headers, body: form || (body === undefined ? undefined : JSON.stringify(body)) });
    } catch (error) {
      // a dropped connection: reads and uploads are tried again (an upload
      // sent twice leaves a spare file at worst)
      if (attempt === 4) throw error;
      await new Promise((ok) => setTimeout(ok, 3000 * attempt));
      continue;
    }
    const text = await response.text();
    if (!response.ok) throw new Error(`${method} ${path}: ${response.status} ${text.slice(0, 300)}`);
    return text ? JSON.parse(text) : null;
  }
}

// The password, not echoed
function askPassword() {
  if (process.env.OWNER_PASSWORD) return Promise.resolve(process.env.OWNER_PASSWORD);
  return new Promise((resolve, reject) => {
    if (!process.stdin.isTTY) return reject(new Error('OWNER_PASSWORD is needed (no terminal to ask it)'));
    process.stdout.write(`Password of ${EMAIL}: `);
    process.stdin.setRawMode(true);
    process.stdin.resume();
    let pw = '';
    process.stdin.on('data', (chunk) => {
      for (const c of chunk.toString('utf8')) {
        if (c === '\r' || c === '\n') {
          process.stdin.setRawMode(false); process.stdin.pause(); process.stdout.write('\n');
          return resolve(pw);
        }
        if (c === '\u0003') { process.stdout.write('\n'); process.exit(130); }
        if (c === '\u007f') pw = pw.slice(0, -1); else pw += c;
      }
    });
  });
}

// Every file of the owner's library, by name
async function library(auth) {
  const byName = new Map();
  for (let page = 1; ; page++) {
    const data = await call('GET', `/upload/files?page=${page}&pageSize=100&sort=createdAt:DESC`, { auth });
    const results = data.results || data;
    for (const f of results) if (!byName.has(f.name)) byName.set(f.name, f);
    const count = data.pagination?.pageCount || 1;
    if (page >= count || !results.length) return byName;
  }
}

const absolute = (url) => (/^https?:\/\//.test(url) ? url : `${API}${url}`);

async function check(urls) {
  let bad = 0;
  for (const [file, url] of Object.entries(urls)) {
    const r = await fetch(url, { method: 'HEAD', headers: { origin: 'null' } }).catch((e) => ({ ok: false, status: e.message, headers: new Headers() }));
    const type = r.headers.get('content-type') || '';
    const cors = r.headers.get('access-control-allow-origin');
    if (!r.ok || !type.startsWith('audio/') || cors !== '*') {
      bad++;
      console.log(`  ✗ ${file}: ${r.status} ${type} ACAO=${cors}`);
    }
  }
  console.log(bad ? `${bad} of ${Object.keys(urls).length} addresses are not right` : `all ${Object.keys(urls).length} addresses answer (audio, CORS *)`);
  return bad;
}

async function main() {
  const files = partFiles();
  const urls = existsSync(URLS) ? JSON.parse(readFileSync(URLS, 'utf8')) : {};
  const missingOnDisk = files.filter((f) => !existsSync(join(PIECES, f)));
  if (missingOnDisk.length) throw new Error(`${missingOnDisk.length} part files are not on disk (make parts): ${missingOnDisk.slice(0, 3).join(', ')}…`);
  const bytes = files.reduce((s, f) => s + readFileSync(join(PIECES, f)).length, 0);
  console.log(`${files.length} part files, ${(bytes / 1048576).toFixed(1)} MB, to ${API} as ${EMAIL || '?'}`);
  if (DRY) {
    files.slice(0, 5).forEach((f) => console.log(`  ${f} -> ${libraryName(f)}`));
    console.log(`  … (${files.length - 5} more); already in media-urls.json: ${files.filter((f) => urls[f]).length}`);
    return;
  }
  if (!EMAIL) throw new Error('--email is needed: the e-mail of the site\'s owner');

  const { data } = await call('POST', '/admin/login', { body: { email: EMAIL, password: await askPassword() } });
  const auth = data.token;
  const have = await library(auth);
  console.log(`logged in; the library has ${have.size} files, ${files.filter((f) => have.has(libraryName(f))).length} of ours`);

  let done = 0, sent = 0;
  const save = () => writeFileSync(URLS, JSON.stringify(Object.fromEntries(Object.entries(urls).sort()), null, 1) + '\n');
  const queue = [...files];
  async function worker() {
    for (let file; (file = queue.shift()); ) {
      const name = libraryName(file);
      let entry = have.get(name);
      if (!entry) {
        const form = new FormData();
        form.append('files', new Blob([readFileSync(join(PIECES, file))], { type: 'audio/mpeg' }), name);
        form.append('fileInfo', JSON.stringify({ name, caption: 'Pinkasol, code tile (picakoch/pinkasol-playground)', alternativeText: null }));
        [entry] = await call('POST', '/upload', { auth, form });
        sent++;
      }
      urls[file] = absolute(entry.url);
      done++;
      if (done % 10 === 0 || done === files.length) {
        save();
        process.stdout.write(`\r${done}/${files.length} (${sent} uploaded)`);
      }
    }
  }
  await Promise.all(Array.from({ length: PARALLEL }, worker));
  save();
  console.log(`\nwrote ${URLS.replace(ROOT + '/', '')}: ${Object.keys(urls).length} addresses (${sent} uploaded now). Next: make tile`);
  if (CHECK && await check(Object.fromEntries(files.map((f) => [f, urls[f]])))) process.exitCode = 1;
}

main().catch((e) => { console.error(`error: ${e.message}`); process.exit(1); });
