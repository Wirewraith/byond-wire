# BYOND Topic protocol: tested implementation reference

## Scope and evidence

Verified on **2026-11-04** against the real server at **127.0.0.1:4999**
specified in [README.md](README.md). It identified itself as Goonstation
Development, BYOND **516.1688**, through the `?type=version` query.

Additional character-encoding tests were performed on **2026-11-09** using an
isolated Windows Dream Daemon **516.1688** on port **5101**. These are described
under [Text encoding](#text-encoding); they did not modify the Goonstation server.

This reference covers TCP Topic exchanges on those builds. Query names and
payload fields belong to the tested Goonstation application, not BYOND itself.

## Transport and exchange

- Open a TCP connection, send one request, read the complete response, then close.
- No handshake, login, HTTP request, or TLS was needed on the tested endpoint.
- Sending the request at once or splitting header/body by 50 ms both worked.
- Batch small binary requests before writing to TCP. On **2026-11-16**, syscall traces against `goondev.goonhub.com:26900` showed Bash's line-buffered `printf` splitting `?who` into writes of 4 and 10 bytes: its body length `00 0a` contains a newline. Disabling Nagle's algorithm removed the extra latency; `?status` was already a single 17-byte write. The Bash client now stages the request in its existing temporary file and sends it with `cat`. TCP may still segment a complete write.
- Reading a response one byte at a time worked. Loop until the declared length is complete; a socket read need not return an entire frame.
- Keep binary data in byte buffers and queries out of executable shell source.

## Request layout

Offsets are zero-based. Hexadecimal values below denote actual bytes, not text
containing escape sequences.

| Offset | Size | Bytes / interpretation |
| --- | --- | --- |
| 0 | 2 | `00 83`, Topic frame signature |
| 2 | 2 | Unsigned big-endian body length `L` |
| 4 | 5 | `00 00 00 00 00`, the tested request prefix |
| 9 | `N` | Query bytes, including the leading `?` when supplied |
| `9 + N` | 1 | `00`, query terminator |

For this tested construction:

```text
L = number_of_query_bytes + 6
request = 00 83 || uint16_be(L) || 00 00 00 00 00 || query_bytes || 00
total_request_bytes = 4 + L
```

`L` excludes the four-byte frame header. Count the bytes actually sent, after
encoding the query. For example, a probe containing UTF-8 `café` had 31 body
bytes; counting text characters instead produced the incorrect length 30.
Both variants returned null for the unknown query. This establishes the byte-count
discrepancy; Unicode handling was checked separately under [Text encoding](#text-encoding).

The two-byte request length was checked beyond 255: the query consisting of
`?protocol_reference=` followed by 280 ASCII `x` bytes produced `L = 306`
(`01 32`) and received a complete null reply. Swapping the two length bytes to
`32 01` produced no response within the test's one-second receive timeout.
Maximum accepted request size was not established.

### Exact request vectors

```text
?status, L = 13:
00 83 00 0d 00 00 00 00 00 3f 73 74 61 74 75 73 00

?ping, L = 11:
00 83 00 0b 00 00 00 00 00 3f 70 69 6e 67 00

?who, L = 10:
00 83 00 0a 00 00 00 00 00 3f 77 68 6f 00

?playing, L = 14:
00 83 00 0e 00 00 00 00 00 3f 70 6c 61 79 69 6e 67 00
```

### Query interpretation observed on this server

| Query bytes | Observed result |
| --- | --- |
| `?status` | Status text |
| `status` | Status text; one leading `?` was optional in this test |
| `??status` | Null |
| `?%73tatus` | Null; percent-encoding the initial `s` did not select `status` |
| `?status&protocol_reference=1` | Null; adding a parameter changed the result |

Clients add one `?` if absent and preserve it if already present. Do not assume a
Topic query is always interpreted as an HTTP query string or that arbitrary
parameters can be appended to a working topic.

The five-zero-byte prefix is a verified working construction, not a claim that
all five bytes are mandatory padding: a separate four-zero-prefix `?status`
request also returned status. A six-zero-prefix variant returned null. These
probes did not establish the meanings of individual prefix bytes; use the
five-zero construction for implementations based on this reference.

## Response layout

| Offset | Size | Bytes / interpretation |
| --- | --- | --- |
| 0 | 2 | `00 83`, Topic frame signature |
| 2 | 2 | Unsigned big-endian body length `L` |
| 4 | 1 | Response type tag |
| 5 | `L - 1` | Type-specific payload |

Read the four-byte header, then exactly `L` body bytes. The type tag is included
in `L`; the header is excluded. A captured status response began `00 83 01 19`:
its body contained **281 bytes**, and the full frame contained **285 bytes**.
This also verifies that response lengths can exceed one byte.

### Observed response types

| Tag | Tested interpretation | Observed body length |
| --- | --- | --- |
| `00` | Null result, no payload | 1 |
| `06` | Text bytes followed by one `00` terminator | Text byte count + 2 |
| `2a` | Little-endian IEEE-754 binary32 numeric payload | 5 |

For text, remove the type tag and final NUL only. The text byte count is
`L - 2`. Empty text and null are distinct observed results. The captured text
responses contained ASCII bytes. The later controlled tests below establish
UTF-8 for normal text on the tested build, with an important formatting exception.

For numbers, decode the four payload bytes explicitly as little-endian float32,
independently of the host machine's byte order. Zero and one were verified:

```text
?ping with zero players:
00 83 00 05 2a 00 00 00 00
               ^ four-byte numeric payload: 0.0

?ping after the user connected a player:
00 83 00 05 2a 00 00 80 3f
               ^ four-byte numeric payload: 1.0
```

The latter payload decoded as little-endian float32 `1.0`; interpreting it as
big-endian float32 gave approximately `4.600603e-41`. Negative, fractional, and
special floating-point values were not exercised.

Exact empty-text and null vectors:

```text
?who with zero players: empty text
00 83 00 02 06 00

?playing: null
00 83 00 01 00
```

`?protocol_reference_unknown` also returned the null vector. A null reply is a
received, complete Topic response, not proof of a transport failure or a
specific application error.

## Text encoding

- Normal text is UTF-8 on the tested modern build. Raw BYOND formatting codes can make the complete payload invalid as strict UTF-8.
- BYOND switched its internal string representation to UTF-8 in version 513: [release notes](https://www.byond.com/docs/notes/513.html), [feature announcement](https://www.byond.com/forum/post/2580951).
- The reference project's [protocol notes](https://github.com/NGGJamie/byond-topics/blob/master/documentation/protocol.txt) specify ASCII requests. Its [Python example](https://github.com/NGGJamie/byond-topics/blob/master/python3/example.py) sends Latin-1 and returns raw response bytes; it does not establish the response encoding.

### Controlled wire tests

- Tested **2026-11-09** with Windows Dream Maker/Dream Daemon **516.1688**, using an isolated world on port **5101**. The Goonstation server on port **4999** was not modified.
- Returned `café|€|Ж|漢|🙂` using Unicode escapes and `ascii2text()`. Both produced UTF-8; UTF-8 query echo preserved the same bytes.
- `list2params()` percent-escaped UTF-8: `é` became `%c3%a9`, consistent with the [DM reference](https://www.byond.com/docs/ref/info.html#/{proc}/list2params).
- `\proper café` returned `ff 15 63 61 66 c3 a9`; `\improper café` returned `ff 16 63 61 66 c3 a9`. These are text payload bytes, excluding the type tag and final NUL.
- BYOND's developer [identifies `0xff` as the format-code marker](https://www.byond.com/forum/post/1768158). It is distinct from Unicode `ÿ`, which returned `c3 bf`.
- Legacy query probes on this Windows build: `e9` became `c3 a9`; `80` became `e2 82 ac`; isolated `ff` survived unchanged. The first two results are consistent with Windows-1252 conversion. Other versions and locales remain untested.
- The macro inventory covers **101 cases**: standalone controls; expanded articles; pronouns for all four genders; ordinals/plurals at several numbers; icons/references; Roman numerals; escaped punctuation/whitespace; all three Unicode escape forms; and legacy styles/colors.
- [Source world](tests/text-macros.dme); [captured payloads and synthetic edge cases](tests/text-vectors.tsv), **434 vectors total**. Offline tests consume exact bytes. Live comparisons normalize dynamic object/resource reference numbers only.
- Reproduce with `python3 tests/capture-text.py`. It compiles temporary files, checks a unique per-run identity, validates all 101 cases, and shuts down its own world.
- Runtime discovery: native `DreamMaker`/`DreamDaemon` commands or the standard Windows installation under WSL. Overrides: `--compiler`, `--daemon`, `--port` (default `5101`).

### Decoder rules

- Remove only the **18 tested two-byte markers** below. Preserve ordinary UTF-8, NUL, newlines, BOM, HTML entities, and markup.
- Validate each UTF-8 run separately. Reject `c3 ff 15 a9`; removing a marker must not join broken character fragments.
- Reject unknown marker codes, trailing `ff`, invalid continuation bytes, overlong encodings, surrogates, truncated sequences, and code points beyond U+10FFFF.
- Shell filters fail with status `1` and empty stdout. Other implementations return or raise decoding errors.
- Keep raw responses when formatting metadata is required. UTF-8 decoding with marker removal is intentionally lossy for that metadata.
- Coverage is specific to the tested version and forms; undocumented and future controls are errors until mapped and tested.

| Bytes | DM forms | Removed metadata |
| --- | --- | --- |
| `ff 06` | `\a`, `\an` without an embedded expression | Article modifier |
| `ff 07` | `\A`, `\An` without an embedded expression | Article modifier |
| `ff 08` | `\the` without an embedded expression | Article modifier |
| `ff 09` | `\The` without an embedded expression | Article modifier |
| `ff 12` | `\...` | Newline suppression |
| `ff 15` | `\proper` | Proper-name flag |
| `ff 16` | `\improper` | Improper-name flag |
| `ff 17` | `\bold`, `\b` | Style |
| `ff 18` | `\italic`, `\i` | Style |
| `ff 19` | `\underline`, `\u` without hexadecimal digits | Style |
| `ff 1f` | `\red` | Color |
| `ff 20` | `\green` | Color |
| `ff 21` | `\blue` | Color |
| `ff 22` | `\black` | Color |
| `ff 23` | `\white` | Color |
| `ff 24` | `\yellow` | Color |
| `ff 25` | `\cyan` | Color |
| `ff 26` | `\magenta` | Color |

- Expanded articles, pronouns, ordinals, plurals, and Roman numerals were ordinary UTF-8 before transmission. `\icon` became an HTML `IMG` tag; `\ref` became an ASCII reference. The decoder preserves those results.
- Compiler acceptance alone does not prove a control exists: `\navy`, `\teal`, and `\normal` became newline/tab escapes followed by literal letters. Those bytes are preserved.

## Application payloads observed

`?status` returned an ASCII parameter string. A captured response body was
`06`, followed by the following text, followed by `00`:

```text
version=Goonstation+13+%28r1%29&host=Wirewraith&gamestate=7&respawn=0&enter=1&round_id=0&ai=1&mode=extended&round_duration=517&shuttle_online=0&shuttle_direction=1&shuttle_location=0&shuttle_timer=360&station_name=Developer+Lounge+%26+Co&map_name=DevTest&map_id=DEVTEST&players=0
```

For this payload, parsing pairs on `&` and applying form-style decoding produced
`version = Goonstation 13 (r1)` and
`station_name = Developer Lounge & Co`. Preserve the raw text at the protocol
layer; parameter parsing belongs to the caller handling this query.

Other verified queries:

| Query | Observed text / value |
| --- | --- |
| `?ping` | Numeric `0.0`, later `1.0` after a player connected |
| `?who` | Empty text while there were no players |
| `?admins` | Text `admins=0` |
| `?mentors` | Text `mentors=0` |
| `?type=version` | Text containing `major=516&minor=1688` and server metadata |
| `?playing` | Null |

## Malformed-request observations

These are individual observations, not a general error-message specification.
In particular, null also occurred for unknown, correctly framed topics.

| Change to the canonical `?status` request | Observed result |
| --- | --- |
| Declare length 12 but transmit the original 13-byte body | Null |
| Declare length 14 but transmit the original 13-byte body | No response within the one-second receive timeout |
| Remove the final NUL and set length to the resulting 12-byte body | Null |
| Change the five-zero prefix to six zeros and update the length | Null |

Earlier live tests sent the original Bash script's backslash-containing arguments
`status&review=hello\nworld` and `status&review=hello\cworld`. Its `echo -ne`
converted the former's `5c 6e` into `0a`, and truncated the latter at `\c`.
The packets declared 33 body bytes but transmitted 32 and 25 respectively.
Both received this non-Topic response:

```text
08 08 28 68 69 74 20 65 6e 74 65 72 20 74 6f 20 63
6f 6e 74 69 6e 75 65 2e 29 ff fc 01 ff fd 1f 0d 0a
```

That capture is not a `00 83` frame. Its readable portion is
`(hit enter to continue.)`. Do not interpret its third and fourth bytes as a
Topic length. That original script returned zero with empty output for both exchanges. Current
clients send queries literally and reject non-Topic responses.

## Limits of this reference

The tests establish a working Topic client exchange with this server/build.
They do not establish other BYOND protocols, authentication, file transfer,
connection reuse, pipelining, maximum accepted sizes, every Unicode/codepage edge case,
embedded-NUL semantics, every prefix field's meaning, all error layouts, or
all numeric values. No universal meaning is assigned to a null application
result. New implementations should test any additional behavior against a real
server before extending this reference.
