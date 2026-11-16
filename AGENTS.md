# Agent instructions

This is a project for communicating with game servers running on the BYOND platform.

The goal is to create small, self contained implementations in various programming languages and frameworks.

- Keep implementations small, readable, and efficient. Use only standard libraries or the documented shell utilities; do not mix implementation languages.
- Build an importable/sourceable library first, with a thin CLI wrapper sharing the same transport logic.
- Follow the [SDK and CLI contract](README.md#examples): decoded native strings by default, distinct numeric/null/empty-text results, and explicit raw-byte access. Shells use byte streams and a separate text filter.
- Library calls return values or errors without printing or exiting. Keep argument parsing, output formatting, and process exit codes in the CLI, following the contract above.
- Apply the [text encoding rules](PROTOCOL.md#text-encoding). Keep marker mappings, decoding policy, and wire evidence in that document.
- Validate inputs and timeout ranges before opening sockets. Use one request deadline across connection attempts and I/O; document blocking OS DNS limitations. Close sockets and release timers/resources on every path.
- Keep application-specific query parsing in the caller.
- Before completion, perform a separate source-size and runtime optimization pass automatically. Remove redundant logic, processes, allocations, I/O, and repeated work while preserving portability, errors, deadlines, cleanup, and regression coverage.
- Compare implementation source bytes before and after. Benchmark performance changes against the previous version under identical typical and large-message workloads.
- After final implementation changes, rerun applicable regression tests and the live-server check below. Report measured improvements, tradeoffs, and unavailable checks. Do not claim minimality or optimality without evidence.
- Read [PROTOCOL.md](PROTOCOL.md) before changing protocol handling. Verify newly discovered wire behavior against a real server and document it there.
- When adding an implementation, add default and raw usage examples to the existing [README.md](README.md) language documentation.
- Keep documentation punchy, clear, and strictly technical. Prefer bullets; update existing coverage in place. Maintain one source of truth for decision records and link to it instead of duplicating it. Do not add superfluous documentation or logs.

## Testing

- Test both direct library calls and CLI behavior, including silent imports, native result types, strict decoding failures, raw-byte preservation, timeouts, fallback, and cleanup.
- Run each decoder against the shared [text vectors](tests/text-vectors.tsv); keep the fixture authoritative instead of copying its cases into each implementation.
- Preserve existing CLI output and exit behavior when modifying a library API.
- Use the following live-server check:

| Name    | Value     |
| ------- | --------- |
| Address | 127.0.0.1 |
| Port    | 4999      |
| Message | status    |

This communicates with a BYOND game server that I'm running locally.
