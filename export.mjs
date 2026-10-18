import Franchise from 'madden-franchise';
import fs from 'node:fs';

const [,, savePath, outPath] = process.argv;
const franchise = await Franchise.create(savePath);
const table = franchise.getTableByName('Player');
await table.readRecords();

const rows = [];
for (const r of table.records) {
  if (r.isEmpty) continue;
  const row = { row: r.index };
  for (const [key, field] of Object.entries(r.fields)) {
    if (field.isReference) continue;
    const v = field.value;
    if (['number', 'string', 'boolean'].includes(typeof v)) row[key] = v;
  }
  rows.push(row);
}
fs.writeFileSync(outPath, JSON.stringify(rows));
console.log('Exported', rows.length, 'players to', outPath);
