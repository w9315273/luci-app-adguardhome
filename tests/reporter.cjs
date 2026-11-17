const { spec } = require('node:test/reporters');
const { Readable } = require('node:stream');
const { stripVTControlCharacters } = require('node:util');

function row(symbol, milliseconds, description) {
 const duration = Number(milliseconds).toFixed(2) + 'ms';
 return symbol + ' ' + duration.padStart(12) + '  ' + description;
}

module.exports = async function* (source) {
 const totals = {};
 for await (const chunk of Readable.from(source).pipe(new spec())) {
  yield chunk.toString().split('\n').map(line => {
   const plain = stripVTControlCharacters(line);
   const result = plain.match(/^\s*([✔✖﹣]) (.*?) \((\d+(?:\.\d+)?)ms\)(.*)$/);
   if (result) return row(result[1] === '✖' ? '✘' : result[1], result[3], result[2] + result[4]);
   const total = plain.match(/^ℹ (tests|suites|pass|fail|cancelled|skipped|todo|duration_ms) (\d+(?:\.\d+)?)$/);
   if (!total) return line;
   totals[total[1]] = Number(total[2]);
   if (total[1] !== 'duration_ms') return null;
   const extras = [['cancelled', '取消'], ['skipped', '跳过'], ['todo', '待完成']]
    .filter(([key]) => totals[key]).map(([key, label]) => ', ' + label + ' ' + totals[key] + ' 项').join('');
   return row(totals.fail || totals.cancelled ? '✘' : '✔', totals.duration_ms,
    '前端测试完成: 共 ' + totals.tests + ' 项, 通过 ' + totals.pass + ' 项, 失败 ' + totals.fail + ' 项' + extras);
  }).filter(line => line !== null).join('\n');
 }
};
