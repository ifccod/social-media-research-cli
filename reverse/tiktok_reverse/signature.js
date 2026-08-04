"use strict";

// 独立实现 webmssdk 2.0.0.507 的 wire 格式。
// 运行时只依赖 Node 内置 crypto 模块。

var crypto = require("crypto");

var ALPHABET =
  "u09tbS3UvgDEe6r-ZVMXzLpsAohTn7mdINQlW412GqBjfYiyk8JORCF5/xKHwacP=";
var TELEMETRY_ALPHABET =
  "Dkdpgh4ZKsQB80/Mfvw36XI1R25+WUAlEi7NLboqYTOPuzmFjJnryx9HVGcaStCe=";
var MAGIC_BYTE = 75;
var TELEMETRY_MAGIC_BYTE = 76;
var SIGMA = [1196819126, 600974999, 3863347763, 1451689750];
var SDK_VERSION = "2.0.0.507";
var SIGNATURE_VERSION = "5.3.0";
var DEFAULT_ENV_CODE = 65;
var DEFAULT_FINGERPRINT_VALUE = 2363850128;
var UBCODE = 14;
var DEFAULT_FINGERPRINT_HASH = "438a26e7";

// X-Dynosaur 使用的十进制数字编码：行表示字符位置，列表示数字 0..9。
var NUMBER_DIGITS = [
  [0xdb, 0xe7, 0xe3, 0xef, 0xeb, 0xf7, 0xf3, 0xff, 0x3b, 0xc7],
  [0xdf, 0xd3, 0xd7, 0xcb, 0xcf, 0xc3, 0xc7, 0x3b, 0xff, 0xf3],
  [0xcb, 0xd7, 0xc3, 0xcf, 0x3b, 0xc7, 0x33, 0x3f, 0xeb, 0xf7],
  [0xcf, 0xc3, 0xd7, 0xcb, 0x3f, 0x33, 0xc7, 0x3b, 0xef, 0xe3],
  [0xcb, 0xd7, 0xd3, 0xdf, 0x3b, 0xc7, 0xc3, 0xcf, 0xeb, 0xf7],
  [0xcf, 0xc3, 0xc7, 0x3b, 0xdf, 0xd3, 0xd7, 0xcb, 0xef, 0xe3],
  [0x3b, 0xc7, 0x33, 0x3f, 0xcb, 0xd7, 0xc3, 0xcf, 0xdb, 0xe7],
  [0x3f, 0x33, 0xc7, 0x3b, 0xcf, 0xc3, 0xd7, 0xcb, 0xdf, 0xd3],
  [0x1b, 0x27, 0x23, 0x2f, 0x2b, 0x37, 0x33, 0x3f, 0x3b, 0xc7],
  [0x9f, 0x93, 0x97, 0x8b, 0x8f, 0x83, 0x87, 0xfb, 0xff, 0xf3],
];

var CHECKSUM_DIGITS = [
  [0x5c, 0x5e, 0x58, 0x5a, 0x54, 0x56, 0x50, 0x52, 0x4c, 0x4e],
  [0x5e, 0x5c, 0x5a, 0x58, 0x56, 0x54, 0x52, 0x50, 0x4e, 0x4c],
  [0x44, 0x46, 0x48, 0x4a, 0x4c, 0x4e, 0x30, 0x32, 0x54, 0x56],
];

var DYNO_TRUE = hexBytes("5ededfe00001");
var DYNO_ZERO = hexBytes("dbdedfe00001");
var DYNO_VERSION = hexBytes("f7a7cfa7cb0005");
var DYNO_SDK_VERSION = hexBytes("e3a7cba7cbb7d73f3f0009");

function u32(value) {
  return value >>> 0;
}

function rotl(value, count) {
  return u32((value << count) | (value >>> (32 - count)));
}

function quarterRound(state, a, b, c, d) {
  state[a] = u32(state[a] + state[b]);
  state[d] = rotl(state[d] ^ state[a], 16);
  state[c] = u32(state[c] + state[d]);
  state[b] = rotl(state[b] ^ state[c], 12);
  state[a] = u32(state[a] + state[b]);
  state[d] = rotl(state[d] ^ state[a], 8);
  state[c] = u32(state[c] + state[d]);
  state[b] = rotl(state[b] ^ state[c], 7);
}

function chachaBlock(initial, rounds) {
  var state = initial.slice();
  var round = 0;
  while (round < rounds) {
    quarterRound(state, 0, 4, 8, 12);
    quarterRound(state, 1, 5, 9, 13);
    quarterRound(state, 2, 6, 10, 14);
    quarterRound(state, 3, 7, 11, 15);
    round += 1;
    if (round >= rounds) break;
    quarterRound(state, 0, 5, 10, 15);
    quarterRound(state, 1, 6, 11, 12);
    quarterRound(state, 2, 7, 12, 13);
    quarterRound(state, 3, 4, 13, 14);
    round += 1;
  }
  for (var index = 0; index < 16; index += 1) {
    state[index] = u32(state[index] + initial[index]);
  }
  return state;
}

function keyWords(keyBytes) {
  var words = [];
  for (var index = 0; index < 12; index += 1) {
    var offset = index * 4;
    words.push(
      u32(
        keyBytes[offset] |
          (keyBytes[offset + 1] << 8) |
          (keyBytes[offset + 2] << 16) |
          (keyBytes[offset + 3] << 24),
      ),
    );
  }
  return words;
}

function deriveRounds(words) {
  var rounds = 0;
  for (var index = 0; index < words.length; index += 1) {
    rounds = (rounds + (words[index] & 15)) & 15;
  }
  return rounds + 5;
}

function chachaXor(input, words, rounds) {
  var output = Uint8Array.from(input);
  var state = SIGMA.concat(words);
  for (var offset = 0; offset < output.length; offset += 64) {
    var stream = chachaBlock(state, rounds);
    state[12] = u32(state[12] + 1);
    var limit = Math.min(64, output.length - offset);
    for (var index = 0; index < limit; index += 1) {
      output[offset + index] ^=
        (stream[index >>> 2] >>> (8 * (index & 3))) & 255;
    }
  }
  return output;
}

function customBase64(bytes, alphabetOverride) {
  var alphabet = alphabetOverride || ALPHABET;
  var output = "";
  var index = 0;
  for (; index + 3 <= bytes.length; index += 3) {
    var value =
      (bytes[index] << 16) | (bytes[index + 1] << 8) | bytes[index + 2];
    output +=
      alphabet[(value >>> 18) & 63] +
      alphabet[(value >>> 12) & 63] +
      alphabet[(value >>> 6) & 63] +
      alphabet[value & 63];
  }
  var remaining = bytes.length - index;
  if (remaining === 1) {
    var one = bytes[index] << 16;
    output += alphabet[(one >>> 18) & 63] + alphabet[(one >>> 12) & 63] + "==";
  } else if (remaining === 2) {
    var two = (bytes[index] << 16) | (bytes[index + 1] << 8);
    output +=
      alphabet[(two >>> 18) & 63] +
      alphabet[(two >>> 12) & 63] +
      alphabet[(two >>> 6) & 63] +
      "=";
  }
  return output;
}

function packEncrypted(plain, keyOverride, magicOverride, alphabetOverride) {
  var key = keyOverride ? Uint8Array.from(keyOverride) : crypto.randomBytes(48);
  if (key.length !== 48) throw new Error("signature key must contain 48 bytes");
  var words = keyWords(key);
  var cipher = chachaXor(plain, words, deriveRounds(words));
  var modulo = cipher.length + 1;
  var insertPosition = 0;
  var index;
  for (index = 0; index < key.length; index += 1) {
    insertPosition = (insertPosition + key[index]) % modulo;
  }
  for (index = 0; index < cipher.length; index += 1) {
    insertPosition = (insertPosition + cipher[index]) % modulo;
  }
  var output = new Uint8Array(1 + cipher.length + key.length);
  output[0] = magicOverride == null ? MAGIC_BYTE : magicOverride;
  output.set(cipher.slice(0, insertPosition), 1);
  output.set(key, 1 + insertPosition);
  output.set(cipher.slice(insertPosition), 1 + insertPosition + key.length);
  return customBase64(output, alphabetOverride);
}

function lzwCompress(value) {
  var text = String(value);
  var dictionary = new Map();
  for (var index = 0; index < 256; index += 1) {
    dictionary.set(String.fromCharCode(index), index);
  }

  var output = [];
  var bitPosition = 0;
  var buffer = 0;
  var bitSize = 8;
  var nextIndex = 255;

  function writeBits(code, length) {
    for (var bit = 0; bit < length; bit += 1) {
      if (code & 1) buffer |= 1 << bitPosition;
      code >>>= 1;
      bitPosition += 1;
      if (bitPosition === 8) {
        output.push(buffer);
        buffer = 0;
        bitPosition = 0;
      }
    }
  }

  var position = 0;
  while (position < text.length) {
    var substring = text[position];
    while (
      position + 1 < text.length &&
      dictionary.has(substring + text[position + 1])
    ) {
      position += 1;
      substring += text[position];
    }
    var code = dictionary.get(substring);
    if (code == null) throw new Error("telemetry input must contain byte characters");
    writeBits(code, bitSize);
    if (position + 1 < text.length) {
      nextIndex += 1;
      dictionary.set(substring + text[position + 1], nextIndex);
      if ((nextIndex & (nextIndex - 1)) === 0) bitSize += 1;
    }
    position += 1;
  }
  if (bitPosition > 0) output.push(buffer);
  return Uint8Array.from(output);
}

function encodeTelemetry(rawJson, keyHex) {
  var key = keyHex ? hexBytes(keyHex) : null;
  return packEncrypted(
    lzwCompress(rawJson),
    key,
    TELEMETRY_MAGIC_BYTE,
    TELEMETRY_ALPHABET,
  );
}

function md5(value) {
  return crypto.createHash("md5").update(String(value), "utf8").digest("hex");
}

function tiktokHash(value) {
  var bytes = Buffer.from(String(value), "utf8");
  var hash = 2166136260;
  for (var index = 0; index < bytes.length; index += 1) {
    hash ^= bytes[index];
    hash = u32(Math.imul(hash, 16777619));
    hash = u32(hash + u32(Math.imul(hash, 32)));
  }
  return hash >>> 0;
}

function uintBytes(value, length) {
  var number = Number(value) >>> 0;
  var output = new Uint8Array(length);
  for (var index = length - 1; index >= 0; index -= 1) {
    output[index] = number & 255;
    number = Math.floor(number / 256);
  }
  return output;
}

function hexBytes(value) {
  var text = String(value);
  if (text.length % 2 !== 0 || !/^[0-9a-f]*$/i.test(text)) {
    throw new Error("invalid hexadecimal input");
  }
  return Uint8Array.from(Buffer.from(text, "hex"));
}

function bytesHex(value) {
  return Buffer.from(value).toString("hex");
}

function appendPadding(output, digitLength) {
  var padding = [0xde, 0xdf, 0xe0];
  for (var index = Math.max(0, digitLength - 1); index < padding.length; index += 1) {
    output.push(padding[index]);
  }
}

function encodeNumber(value) {
  var text = String(Math.trunc(Number(value)));
  if (!/^\d{1,10}$/.test(text)) throw new Error("Dynosaur integer is outside uint32 range");
  var output = [];
  for (var index = 0; index < text.length; index += 1) {
    output.push(NUMBER_DIGITS[index][Number(text[index])]);
  }
  appendPadding(output, text.length);
  output.push((text.length >>> 8) & 255, text.length & 255);
  return Uint8Array.from(output);
}

function encodeChecksum(value) {
  var text = String(value >>> 0);
  if (!/^\d{1,3}$/.test(text)) throw new Error("Dynosaur checksum is outside uint8 range");
  var output = [];
  for (var index = 0; index < text.length; index += 1) {
    output.push(CHECKSUM_DIGITS[index][Number(text[index])]);
  }
  appendPadding(output, text.length);
  output.push((text.length >>> 8) & 255, text.length & 255);
  return Uint8Array.from(output);
}

function concatBytes(parts) {
  var size = 0;
  var index;
  for (index = 0; index < parts.length; index += 1) size += parts[index].length;
  var output = new Uint8Array(size);
  var offset = 0;
  for (index = 0; index < parts.length; index += 1) {
    output.set(parts[index], offset);
    offset += parts[index].length;
  }
  return output;
}

function normalizeCounters(options) {
  var source = (options && options.counters) || {};
  return {
    txr: Number(source.txr == null ? 24 : source.txr) >>> 0,
    tfr: Number(source.tfr == null ? 0 : source.tfr) >>> 0,
    ixr: Number(source.ixr == null ? 28 : source.ixr) >>> 0,
    ifr: Number(source.ifr == null ? 0 : source.ifr) >>> 0,
    dynosaurIxr: Number(
      source.dynosaurIxr == null ? 4 : source.dynosaurIxr,
    ) >>> 0,
  };
}

function randomUint16(override) {
  return override == null
    ? crypto.randomBytes(2).readUInt16BE(0)
    : Number(override) & 65535;
}

function randomUint32(override) {
  return override == null
    ? crypto.randomBytes(4).readUInt32BE(0)
    : Number(override) >>> 0;
}

function randomState(options) {
  var envCode = Number(options.envCode == null ? DEFAULT_ENV_CODE : options.envCode) & 65535;
  var timestampMs = Number(options.timestampMs == null ? Date.now() : options.timestampMs);
  var baseMicroseconds =
    options.microseconds == null
      ? timestampMs * 1000 + randomUint16(null) % 1000
      : Number(options.microseconds);
  var microsecondDelta =
    options.microsecondDelta == null
      ? 1 + randomUint16(null) % 2048
      : Number(options.microsecondDelta);
  return {
    envCode: envCode,
    dynosaurField36: u32(
      (envCode << 16) |
        randomUint16(
          options.dynosaurRandomLow16 == null
            ? options.randomLow16
            : options.dynosaurRandomLow16,
        ),
    ),
    dynosaurMicrotime: u32(baseMicroseconds % 0x80000000),
    gnarlyField14: u32(
      (envCode << 16) |
        randomUint16(
          options.gnarlyRandomLow16 == null
            ? options.randomLow16
            : options.gnarlyRandomLow16,
        ),
    ),
    gnarlyField15: randomUint32(
      options.gnarlyRandom32 == null ? options.random32 : options.gnarlyRandom32,
    ),
    gnarlyMicrotime: u32((baseMicroseconds + microsecondDelta) % 0x80000000),
  };
}

function buildDynosaurValues(rawQuery, body, userAgent, state, options) {
  var counters = normalizeCounters(options);
  var timestampMs = Number(options.timestampMs == null ? Date.now() : options.timestampMs);
  var fingerprintHash = options.fingerprintHash || DEFAULT_FINGERPRINT_HASH;
  var fingerprintValue = Number(
    options.fingerprintValue == null
      ? DEFAULT_FINGERPRINT_VALUE
      : options.fingerprintValue,
  ) >>> 0;
  var values = [
    DYNO_TRUE,
    DYNO_TRUE,
    DYNO_TRUE,
    DYNO_ZERO,
    encodeNumber(state.dynosaurField36),
    encodeNumber(counters.dynosaurIxr),
    encodeNumber(state.envCode),
    encodeNumber(Math.floor(timestampMs / 1000)),
    encodeNumber(counters.tfr),
    encodeNumber(counters.ifr),
    DYNO_VERSION,
    uintBytes(tiktokHash(body), 4),
    encodeNumber(fingerprintValue),
    DYNO_ZERO,
    uintBytes(tiktokHash(rawQuery), 4),
    encodeNumber(counters.txr),
    uintBytes(tiktokHash(userAgent), 4),
    DYNO_SDK_VERSION,
    DYNO_ZERO,
    DYNO_ZERO,
    encodeNumber(state.dynosaurMicrotime),
    DYNO_ZERO,
    encodeNumber(UBCODE),
    DYNO_ZERO,
    hexBytes(fingerprintHash),
  ];

  var checksum = 0;
  for (var index = 0; index < values.length; index += 1) checksum ^= values[index][1];
  values[0] = encodeChecksum(checksum & 255);
  return values;
}

function serializeDynosaur(values) {
  var parts = [];
  for (var index = 0; index < values.length; index += 1) {
    var value = values[index];
    parts.push(Uint8Array.from([32 + index, (value.length >>> 8) & 255, value.length & 255]));
    parts.push(value);
  }
  return concatBytes(parts);
}

function buildDynosaur(rawQuery, body, userAgent, state, options) {
  var values = buildDynosaurValues(rawQuery, body, userAgent, state, options);
  var key = options.dynosaurKeyHex ? hexBytes(options.dynosaurKeyHex) : null;
  return packEncrypted(serializeDynosaur(values), key);
}

var GNARLY_ORDER = [9, 7, 11, 12, 16, 13, 10, 8, 1, 5, 15, 4, 3, 2, 6, 14, 0];
var GNARLY_SMALL_INTS = { 1: true, 2: true, 11: true, 12: true, 13: true };

function serializeGnarly(fields) {
  var output = [GNARLY_ORDER.length];
  for (var index = 0; index < GNARLY_ORDER.length; index += 1) {
    var field = GNARLY_ORDER[index];
    var value = fields[field];
    var bytes;
    if (typeof value === "string") {
      bytes = Uint8Array.from(Buffer.from(value, "utf8"));
    } else {
      bytes = uintBytes(value, GNARLY_SMALL_INTS[field] ? 2 : 4);
    }
    output.push(field, (bytes.length >>> 8) & 255, bytes.length & 255);
    for (var byteIndex = 0; byteIndex < bytes.length; byteIndex += 1) {
      output.push(bytes[byteIndex]);
    }
  }
  return Uint8Array.from(output);
}

function stringPrefixUint32(value) {
  var bytes = Buffer.from(String(value), "utf8");
  var output = 0;
  for (var index = 0; index < Math.min(bytes.length, 4); index += 1) {
    output = u32((output << 8) | bytes[index]);
  }
  return output;
}

function companionChecksum(fields) {
  var checksum = 0;
  Object.keys(fields).forEach(function (field) {
    var value = fields[field];
    if (typeof value === "number") {
      checksum = u32(checksum ^ value);
    } else if (typeof value === "string") {
      checksum = u32(checksum ^ stringPrefixUint32(value));
    }
  });
  return checksum;
}

function buildGnarly(query, body, userAgent, state, options) {
  var counters = normalizeCounters(options);
  var timestampMs = Number(options.timestampMs == null ? Date.now() : options.timestampMs);
  var fingerprintValue = Number(
    options.fingerprintValue == null
      ? DEFAULT_FINGERPRINT_VALUE
      : options.fingerprintValue,
  ) >>> 0;
  var fields = {
    1: state.envCode,
    2: UBCODE,
    3: md5(query),
    4: md5(body),
    5: md5(userAgent),
    6: Math.floor(timestampMs / 1000),
    7: fingerprintValue,
    8: state.gnarlyMicrotime,
    9: SIGNATURE_VERSION,
    10: SDK_VERSION,
    11: 1,
    12: counters.txr + counters.tfr,
    13: counters.ixr + counters.ifr,
    14: state.gnarlyField14,
    15: state.gnarlyField15,
  };
  fields[16] = companionChecksum(fields);
  var xorHeader = 0;
  Object.keys(fields).forEach(function (field) {
    if (typeof fields[field] === "number") xorHeader = u32(xorHeader ^ fields[field]);
  });
  fields[0] = xorHeader;
  var key = options.gnarlyKeyHex ? hexBytes(options.gnarlyKeyHex) : null;
  return {
    value: packEncrypted(serializeGnarly(fields), key),
    queryMd5: fields[3],
    fields: fields,
  };
}

function signQuery(rawQuery, inputOptions) {
  var options = inputOptions || {};
  var body = options.body == null ? "" : String(options.body);
  var userAgent = String(options.userAgent || "");
  var msToken = String(options.msToken || "");
  if (rawQuery == null) throw new Error("rawQuery is required");
  if (!userAgent) throw new Error("userAgent is required");
  var normalizedQuery = String(rawQuery).replace(/^\?/, "");
  var timestampMs = Number(options.timestampMs == null ? Date.now() : options.timestampMs);
  options.timestampMs = timestampMs;
  var state = randomState(options);
  var dynosaur = buildDynosaur(normalizedQuery, body, userAgent, state, options);
  var gnarlyInput =
    (normalizedQuery ? normalizedQuery + "&" : "") +
    "X-Dynosaur=" +
    dynosaur +
    "&msToken=" +
    msToken;
  var gnarly = buildGnarly(gnarlyInput, body, userAgent, state, options);
  return {
    query: gnarlyInput + "&X-Bogus=1&X-Gnarly=" + gnarly.value,
    xDynosaur: dynosaur,
    xGnarly: gnarly.value,
    xBogus: "1",
    baseQueryHash: tiktokHash(normalizedQuery).toString(16).padStart(8, "0"),
    gnarlyQueryMd5: gnarly.queryMd5,
  };
}

function hashHex(value) {
  return tiktokHash(value).toString(16).padStart(8, "0");
}

function encodeNumberHex(value) {
  return bytesHex(encodeNumber(value));
}

function encodeChecksumHex(value) {
  return bytesHex(encodeChecksum(value));
}

function dynosaurPlainHex(rawQuery, inputOptions) {
  var options = inputOptions || {};
  var state = randomState(options);
  var values = buildDynosaurValues(
    String(rawQuery).replace(/^\?/, ""),
    options.body == null ? "" : String(options.body),
    String(options.userAgent || ""),
    state,
    options,
  );
  return bytesHex(serializeDynosaur(values));
}

function gnarlyPlainHex(query, inputOptions) {
  var options = inputOptions || {};
  var state = randomState(options);
  var result = buildGnarly(
    String(query).replace(/^\?/, ""),
    options.body == null ? "" : String(options.body),
    String(options.userAgent || ""),
    state,
    options,
  );
  var fields = result.fields;
  return bytesHex(serializeGnarly(fields));
}
