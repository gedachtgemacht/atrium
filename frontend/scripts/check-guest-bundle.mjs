// The guest bundle must not carry the internal app's words (wall rule 5). Run after `npm run build`.
import { readFileSync, readdirSync } from 'node:fs'

const html = readFileSync('dist/guest.html', 'utf8')
const files = new Set()
for (const m of html.matchAll(/(?:src|href)="\/assets\/([^"]+\.js)"/g)) files.add(m[1])
// Follow static imports of the entry chunk.
for (const f of [...files]) {
  const src = readFileSync(`dist/assets/${f}`, 'utf8')
  for (const m of src.matchAll(/from\s*"\.\/([^"]+\.js)"|import\s*"\.\/([^"]+\.js)"/g)) files.add(m[1] || m[2])
}
const words = ['Backroom', 'backroom', 'Hinterzimmer', 'QuoteAgent', 'Angebotsagent', 'Pull into', 'reinholen', '/api/drafts', 'work_result', 'memory_marks']
let bad = 0
for (const f of files) {
  const src = readFileSync(`dist/assets/${f}`, 'utf8')
  for (const w of words) if (src.includes(w)) { console.error(`guest bundle ${f} contains "${w}"`); bad++ }
}
if (!files.size) { console.error('no guest chunks found'); process.exit(1) }
if (bad) process.exit(1)
console.log(`guest bundle clean (${files.size} files: ${[...files].join(', ')})`)
void readdirSync
