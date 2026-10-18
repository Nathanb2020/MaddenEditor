import Franchise from 'madden-franchise';
import fs from 'node:fs';

const [,, savePath, editsPath, outPath] = process.argv;
const edits = JSON.parse(fs.readFileSync(editsPath, 'utf8'));

const franchise = await Franchise.create(savePath);
const table = franchise.getTableByName('Player');
await table.readRecords();

let changed = 0;
for (const { row, ...fields } of edits) {
  const rec = table.records[row];
  if (!rec || rec.isEmpty) { console.warn('Skipping bad row', row); continue; }
  for (const [k, v] of Object.entries(fields)) { rec[k] = v; changed++; }
}
await franchise.save(outPath);
console.log('Applied', changed, 'field edits ->', outPath);
