#!/usr/bin/env node
'use strict';
// Built-ins only. Exit: 0 value, 1 error, 2 null, 124 network timeout.
const net = require('node:net');

// Remove tested BYOND markers; HTML and literal Unicode remain intact.
const textDecoder = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true });
const textMarkers = new Set([0x06, 0x07, 0x08, 0x09, 0x12, 0x15, 0x16, 0x17, 0x18, 0x19, 0x1f, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26]);
function decodeText(data) {
  let text = '', start = 0, marker;
  while ((marker = data.indexOf(255, start)) !== -1) {
    text += textDecoder.decode(data.subarray(start, marker));
    if (!textMarkers.has(data[marker + 1]))
      throw new Error('Unknown or truncated BYOND text marker');
    start = marker + 2;
  }
  return text + textDecoder.decode(data.subarray(start));
}

function topic(host, port, query, timeout = 5000) {
  return topicRaw(host, port, query, timeout).then(value =>
    Buffer.isBuffer(value) ? decodeText(value) : value);
}

async function topicRaw(host, port, query, timeout = 5000) {
  if (!host || !Number.isInteger(port) || port < 1 || port > 65535)
    throw new Error('Invalid address or port');
  if (!Number.isFinite(timeout) || timeout < 1 || timeout > 2147483647)
    throw new RangeError('Timeout must be between 1 and 2147483647 milliseconds');
  if (!query.startsWith('?')) query = '?' + query;
  if (query.includes('\0')) throw new Error('Query contains NUL');
  const size = Buffer.byteLength(query);
  if (size + 6 > 65535) throw new Error('Query exceeds two-byte frame length');
  const request = Buffer.alloc(size + 10);
  request.writeUInt16BE(0x83, 0);
  request.writeUInt16BE(size + 6, 2);
  request.write(query, 9);

  return new Promise((resolve, reject) => {
    const socket = net.createConnection({ host, port });
    let received = Buffer.allocUnsafe(4), offset = 0, length, finished = false;
    const timer = setTimeout(() => finish(Object.assign(
      new Error('Topic request timed out'), { code: 'ETIMEDOUT' })), timeout);
    function finish(error, value) {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      socket.destroy();
      if (error) reject(error);
      else resolve(value);
    }
    socket.on('error', finish);
    socket.on('close', () => finish(new Error('Incomplete Topic response')));
    socket.on('connect', () => socket.write(request));
    socket.on('data', chunk => {
      while (chunk.length && !finished) {
        const count = Math.min(chunk.length, received.length - offset);
        chunk.copy(received, offset, 0, count);
        offset += count;
        chunk = chunk.subarray(count);
        if (offset < received.length) return;
        if (length === undefined) {
          if (received.readUInt16BE(0) !== 0x83) return finish(new Error('Non-Topic response'));
          length = received.readUInt16BE(2);
          if (!length) return finish(new Error('Empty Topic body'));
          received = Buffer.allocUnsafe(length);
          offset = 0;
          continue;
        }
        const body = received;
        if (body[0] === 0 && length === 1) finish(null, null);
        else if (body[0] === 6 && length >= 2 && body[length - 1] === 0)
          finish(null, body.subarray(1, -1));
        else if (body[0] === 42 && length === 5) finish(null, body.readFloatLE(1));
        else finish(new Error('Invalid Topic response'));
      }
    });
  });
}

topic.raw = topicRaw;
topic.decodeText = decodeText;
module.exports = topic;
if (require.main === module) {
  (async () => {
    if (process.argv.length !== 5)
      throw new Error(`Usage: ${process.argv[1]} <address> <port> <message>`);
    const result = await topicRaw(process.argv[2], Number(process.argv[3]), process.argv[4]);
    if (result === null) process.exitCode = 2;
    else process.stdout.write(Buffer.isBuffer(result) ? result : String(result));
  })().catch(error => {
    console.error(error.message);
    process.exitCode = error.code === 'ETIMEDOUT' ? 124 : 1;
  });
}
