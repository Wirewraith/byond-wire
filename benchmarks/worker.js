const topic = require('../nodejs/byond-wire.js');
const lines = require('node:readline').createInterface({input: process.stdin});
(async () => {
  for await (const line of lines) {
    const [mode, query] = line.split('\t');
    const start = process.hrtime.bigint();
    try {
      const value = await (mode === 'raw' ? topic.raw : topic)(process.argv[2], Number(process.argv[3]), query);
      const ms = Number(process.hrtime.bigint() - start) / 1e6;
      const kind = value === null ? 'null' : typeof value === 'number' ? 'number' : 'text';
      if (kind === 'text' && (mode === 'raw' ? !Buffer.isBuffer(value) : typeof value !== 'string')) throw new Error('incorrect native text type');
      console.log(`${ms}\t${kind}\t${kind === 'null' ? 0 : kind === 'number' ? 4 : Buffer.byteLength(value)}`);
    } catch (error) {
      console.log(`${Number(process.hrtime.bigint() - start) / 1e6}\terror\t${String(error).replace(/[\r\n]/g, ' ')}`);
    }
  }
})();
