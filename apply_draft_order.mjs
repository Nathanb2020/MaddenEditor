import Franchise from 'madden-franchise';
import fs from 'node:fs';

const [,, savePath, editsPath, outPath] = process.argv;
if (!savePath || !editsPath || !outPath) {
  throw new Error('Usage: apply_draft_order.mjs SAVE EDITS.json OUTPUT');
}

const edits = JSON.parse(fs.readFileSync(editsPath, 'utf8'));
const franchise = await Franchise.create(savePath);
const playerTable = franchise.getTableByName('Player');
const draftTable = franchise.getTableByName('DraftPlayer');
const evaluationTable = franchise.getTableByName('DraftBoardPlayerEvaluation');
const boardArrayTable = franchise.getTableByName('DraftBoardPlayerEvaluation[]');
await playerTable.readRecords();
await draftTable.readRecords();
await evaluationTable.readRecords();
await boardArrayTable.readRecords();

function apply(table, rows, label) {
  const seen = new Set();
  let changed = 0;
  for (const { row, ...fields } of rows) {
    if (seen.has(row)) throw new Error(`Duplicate ${label} edit row ${row}.`);
    seen.add(row);
    const record = table.records[row];
    if (!record || record.isEmpty) throw new Error(`Invalid ${label} edit row ${row}.`);
    for (const [key, value] of Object.entries(fields)) {
      if (!record.fields[key]) throw new Error(`Missing ${label} field ${key} at row ${row}.`);
      record[key] = value;
      changed++;
    }
  }
  return changed;
}

const playerChanges = apply(playerTable, edits.players, 'Player');
const draftChanges = apply(draftTable, edits.draftPlayers, 'DraftPlayer');
const evaluationChanges = apply(evaluationTable, edits.evaluations, 'DraftBoardPlayerEvaluation');

const seenBoards = new Set();
for (const { row, refs } of edits.boards) {
  if (seenBoards.has(row)) throw new Error(`Duplicate team-board row ${row}.`);
  seenBoards.add(row);
  const record = boardArrayTable.records[row];
  if (!record || record.isEmpty || record.arraySize !== refs.length) {
    throw new Error(`Invalid team-board row ${row} or prospect count mismatch.`);
  }
  const fields = Object.entries(record.fields)
    .filter(([, field]) => field.isReference && field.offset.index < record.arraySize)
    .sort((a, b) => a[1].offset.index - b[1].offset.index);
  if (fields.length !== refs.length) throw new Error(`Team-board row ${row} has an unexpected array size.`);
  refs.forEach((evaluationRow, index) => {
    record[fields[index][0]] = evaluationTable.getBinaryReferenceToRecord(evaluationRow);
  });
}
await franchise.save(outPath);
console.log(`Applied ${playerChanges} Player, ${draftChanges} DraftPlayer, and `
  + `${evaluationChanges} evaluation fields; reordered ${seenBoards.size} team boards -> ${outPath}`);
