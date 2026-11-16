'use strict';
// Run with: node --test nodejs/test-byond-wire.js
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const net = require('node:net');
const { test } = require('node:test');
const { setTimeout: delay } = require('node:timers/promises');
const script = require('node:path').join(__dirname, 'byond-wire.js');

function frame(body) {
  const header = Buffer.from([0, 0x83, 0, 0]);
  header.writeUInt16BE(body.length, 2);
  return Buffer.concat([header, body]);
}

function invoke(args) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [script, ...args], { timeout: 7000 });
    const out = [], err = [];
    child.stdout.on('data', chunk => out.push(chunk));
    child.stderr.on('data', chunk => err.push(chunk));
    child.on('error', reject);
    child.on('close', code => resolve({ code, out: Buffer.concat(out), err: Buffer.concat(err) }));
  });
}

async function server(reply, options, run) {
  let request = Buffer.alloc(0), sent = false;
  const sockets = new Set();
  const listener = net.createServer(socket => {
    sockets.add(socket);
    socket.on('error', () => {});
    socket.on('close', () => sockets.delete(socket));
    socket.on('data', async chunk => {
      request = Buffer.concat([request, chunk]);
      if (sent || request.length < 4 || request.length < 4 + request.readUInt16BE(2)) return;
      sent = true;
      const chunks = options.fragment ? Array.from(reply, byte => Buffer.from([byte])) : [reply];
      for (const part of chunks) {
        if (options.delay) await delay(options.delay);
        if (socket.destroyed) return;
        socket.write(part);
      }
      if (!options.hold) socket.end();
    });
  });
  await new Promise(resolve => listener.listen(0, '127.0.0.1', resolve));
  try {
    await run(listener.address().port, () => request);
  } finally {
    for (const socket of sockets) socket.destroy();
    await new Promise(resolve => listener.close(resolve));
  }
}

async function exchange(query, reply, output = Buffer.alloc(0), code = 0, options = {}) {
  await server(reply, options, async (port, request) => {
    const result = await invoke(['127.0.0.1', String(port), query]);
    assert.equal(result.code, code, result.err.toString());
    assert.deepEqual(result.out, Buffer.from(output));
    const bytes = Buffer.from(query.startsWith('?') ? query : '?' + query);
    assert.deepEqual(request(), frame(Buffer.concat([Buffer.alloc(5), bytes, Buffer.alloc(1)])));
    assert.equal(result.err.length > 0, code === 1);
  });
}

test('canonical wire request and text output', async () => {
  await server(Buffer.from('0083000406686900', 'hex'), {}, async (port, request) => {
    const result = await invoke(['127.0.0.1', String(port), 'status']);
    assert.equal(result.code, 0, result.err.toString());
    assert.equal(result.out.toString(), 'hi');
    assert.deepEqual(request(), Buffer.from('0083000d00000000003f73746174757300', 'hex'));
  });
});

test('text bytes, empty text, null and little-endian numbers', async () => {
  for (const [body, output, code] of [
    [Buffer.from([6, 0]), '', 0], [Buffer.from([0]), '', 2],
    [Buffer.from([6, 97, 10, 92, 255, 10, 0]), Buffer.from([97, 10, 92, 255, 10]), 0],
    [Buffer.from('2a0000803f', 'hex'), '1', 0],
    [Buffer.from('2a00000000', 'hex'), '0', 0],
    [Buffer.from('2a000020c0', 'hex'), '-2.5', 0],
    [Buffer.concat([Buffer.from([6]), Buffer.alloc(65533, 120), Buffer.alloc(1)]), Buffer.alloc(65533, 120), 0],
  ]) await exchange('status', frame(body), output, code);
});

test('queries preserve UTF-8, literal shell characters and length boundaries', async () => {
  for (const query of ['?status', '??status', '', 'café',
    "status'; printf MARKER; #$(printf MARKER)`id`\\n\\c*?[a-z]",
    'x'.repeat(280), 'x'.repeat(65528), '?' + 'x'.repeat(65528)]) {
    await exchange(query, frame(Buffer.from([0])), '', 2);
  }
});

test('rejects malformed or incomplete replies', async () => {
  for (const reply of [Buffer.alloc(0), Buffer.from('008300', 'hex'),
    Buffer.from('ffff000100', 'hex'), frame(Buffer.alloc(0)),
    frame(Buffer.from([6])), frame(Buffer.from([6, 97])), frame(Buffer.from([7])),
    frame(Buffer.from([0, 0])), frame(Buffer.from([42, 0])),
    Buffer.from('0083000a06616263', 'hex')]) {
    await exchange('status', reply, '', 1);
  }
});

test('fragmented response completes without waiting for server EOF', async () => {
  await exchange('status', frame(Buffer.from([6, 104, 105, 0])), 'hi', 0,
    { fragment: true, delay: 10, hold: true });
});

test('bad CLI arguments and oversized queries fail cleanly', async () => {
  for (const args of [[], ['host'], ['', '4999', 'status'],
    ['127.0.0.1', '0', 'status'], ['127.0.0.1', '65536', 'status'],
    ['127.0.0.1', '1.5', 'status'], ['127.0.0.1', 'x', 'status'],
    ['127.0.0.1', '1', 'x'.repeat(65529)], ['127.0.0.1', '1', 'é'.repeat(32765)]]) {
    const result = await invoke(args);
    assert.equal(result.code, 1);
    assert.equal(result.out.length, 0);
    assert.ok(result.err.length);
    assert.doesNotMatch(result.err.toString(), /at .*:\d+:\d+/);
  }
});

test('connection refusal fails cleanly', async () => {
  const listener = net.createServer();
  await new Promise(resolve => listener.listen(0, '127.0.0.1', resolve));
  const port = listener.address().port;
  await new Promise(resolve => listener.close(resolve));
  const result = await invoke(['127.0.0.1', String(port), 'status']);
  assert.equal(result.code, 1);
  assert.equal(result.out.length, 0);
  assert.ok(result.err.length);
});

test('CLI times out and releases its socket', async () => {
  await server(Buffer.alloc(0), { hold: true }, async port => {
    const result = await invoke(['127.0.0.1', String(port), 'status']);
    assert.equal(result.code, 124, result.err.toString());
    assert.equal(result.out.length, 0);
    assert.match(result.err.toString(), /timed out/);
  });
});

test('API rejects embedded NUL and enforces a total deadline during trickle replies', async () => {
  const topic = require(script);
  await assert.rejects(topic('127.0.0.1', 1, 'status\0ignored'), /NUL/);
  await server(frame(Buffer.from([6, 104, 105, 0])),
    { fragment: true, delay: 30, hold: true }, async port => {
      const start = performance.now();
      await assert.rejects(topic('127.0.0.1', port, 'status', 120), { code: 'ETIMEDOUT' });
      assert.ok(performance.now() - start < 500);
    });
});


test('imported API preserves response types and raw bytes', async () => {
  const topic = require(script);
  for (const [body, expected] of [
    [Buffer.from([6, 255, 0]), Buffer.from([255])],
    [Buffer.from([6, 0]), Buffer.alloc(0)],
    [Buffer.from([0]), null], [Buffer.from('2a000020c0', 'hex'), -2.5],
  ]) await server(frame(body), { fragment: true, hold: true }, async port => {
    assert.deepEqual(await topic.raw('127.0.0.1', port, 'status'), expected);
  });
});


test('invalid timeout values reject before creating a socket', async t => {
  const topic = require(script);
  const connect = t.mock.method(net, 'createConnection', () => {
    throw new Error('Connection attempted before timeout validation');
  });
  for (const timeout of [1n, '5000', null, NaN, Infinity, -Infinity, 0, -1, .5, 2147483648]) {
    await assert.rejects(topic('127.0.0.1', 4999, 'status', timeout), RangeError);
  }
  assert.equal(connect.mock.callCount(), 0);
});

test('largest supported timeout can complete normally', async () => {
  const topic = require(script);
  await server(frame(Buffer.from([6, 104, 105, 0])), { delay: 20 }, async port => {
    assert.deepEqual(await topic('127.0.0.1', port, 'status', 2147483647), 'hi');
  });
});


test('BYOND text decoder matches captured macro and malformed-byte vectors', () => {
  const { decodeText } = require(script);
  const fs = require('node:fs'), path = require('node:path');
  const fixture = path.join(__dirname, '../tests/text-vectors.tsv');
  const vectors = fs.readFileSync(fs.existsSync(fixture) ? fixture : path.join(__dirname, 'tests/text-vectors.tsv'), 'utf8');
  for (const line of vectors.trimEnd().split('\n')) {
    if (line.startsWith('#')) continue;
    const [name, hex, expected] = line.split('\t');
    const data = Buffer.from(hex, 'hex'), original = Buffer.from(data);
    if (expected === '-') assert.throws(() => decodeText(data), undefined, name);
    else assert.equal(decodeText(data), Buffer.from(expected, 'hex').toString('utf8'), name);
    assert.deepEqual(data, original, name + ' mutated input');
  }
  assert.equal(decodeText(Buffer.alloc(65533, 120)), 'x'.repeat(65533));
});


test('default API returns decoded strings and rejects malformed text', async () => {
  const topic = require(script);
  for (const [body, expected] of [
    [Buffer.from('06ff16636166c3a900', 'hex'), 'café'],
    [Buffer.from([6, 0]), ''], [Buffer.from([0]), null],
    [Buffer.from('2a000020c0', 'hex'), -2.5],
  ]) await server(frame(body), { hold: true }, async port => {
    assert.equal(await topic('127.0.0.1', port, 'status'), expected);
  });
  for (const hex of ['ff', 'ff1b', 'c3ff15a9']) {
    await server(frame(Buffer.concat([Buffer.from([6]), Buffer.from(hex, 'hex'), Buffer.alloc(1)])),
      { hold: true }, async port => {
        await assert.rejects(topic('127.0.0.1', port, 'status'));
      });
  }
});
