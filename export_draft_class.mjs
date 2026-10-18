import Franchise from 'madden-franchise';
import fs from 'node:fs';

const [,, savePath, outPath] = process.argv;
if (!savePath || !outPath) throw new Error('Usage: export_draft_class.mjs SAVE OUTPUT.json');

const franchise = await Franchise.create(savePath);
const playerTable = franchise.getTableByName('Player');
const draftTable = franchise.getTableByName('DraftPlayer');
const evaluationTable = franchise.getTableByName('DraftBoardPlayerEvaluation');
const boardArrayTable = franchise.getTableByName('DraftBoardPlayerEvaluation[]');
if (!playerTable || !draftTable || !evaluationTable || !boardArrayTable) {
  throw new Error('This save is missing a Player, DraftPlayer, or draft-board table.');
}
await playerTable.readRecords();
await draftTable.readRecords();
await evaluationTable.readRecords();
await boardArrayTable.readRecords();

function scalarFields(record) {
  const result = {};
  for (const [key, field] of Object.entries(record.fields)) {
    const value = field.value;
    if (['number', 'string', 'boolean'].includes(typeof value)) result[key] = value;
  }
  return result;
}

const playerRows = new Map();
const players = [];
for (const [row, record] of playerTable.records.entries()) {
  if (record.isEmpty) continue;
  playerRows.set(record, row);
  const data = scalarFields(record);
  data.row = row;
  // College is a packed franchise reference, retained as a stable program key.
  data.College = record.College ?? '';
  players.push(data);
}

const draftPlayers = [];
const draftRowsByRecord = new Map();
for (const [row, record] of draftTable.records.entries()) {
  if (record.isEmpty) continue;
  const linkedPlayer = franchise.getReferencedRecord(record.Player);
  const playerRow = playerRows.get(linkedPlayer);
  if (playerRow === undefined) continue;
  const data = scalarFields(record);
  data.row = row;
  data.playerRow = playerRow;
  draftPlayers.push(data);
  draftRowsByRecord.set(record, row);
}

const evaluations = [];
const evaluationRows = new Map();
for (const [row, record] of evaluationTable.records.entries()) {
  if (record.isEmpty) continue;
  const draftPlayer = franchise.getReferencedRecord(record.DraftPlayer);
  const draftPlayerRow = draftRowsByRecord.get(draftPlayer);
  if (draftPlayerRow === undefined) continue;
  const data = scalarFields(record);
  data.row = row;
  data.draftPlayerRow = draftPlayerRow;
  evaluations.push(data);
  evaluationRows.set(record, row);
}

const boards = [];
for (const [row, record] of boardArrayTable.records.entries()) {
  if (record.isEmpty) continue;
  const refs = Object.entries(record.fields)
    .filter(([, field]) => field.isReference && field.offset.index < record.arraySize)
    .sort((a, b) => a[1].offset.index - b[1].offset.index)
    .map(([, field]) => evaluationRows.get(franchise.getReferencedRecord(field.value)))
    .filter(value => value !== undefined);
  boards.push({ row, refs });
}

fs.writeFileSync(outPath, JSON.stringify({ gameYear: franchise.gameYear, players, draftPlayers, evaluations, boards }));
console.log(`Exported ${players.length} players, ${draftPlayers.length} draft-player records, `
  + `${evaluations.length} team evaluations, and ${boards.length} team boards.`);
