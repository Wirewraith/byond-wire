// Standalone CLI; the reusable implementation lives in byond-wire.rs.
#[path = "byond-wire.rs"]
mod byond;
pub use byond::{decode_text, topic};
use byond::{topic_raw, RawResponse};
use std::io::{self, Write};
use std::time::Duration;

fn run(args: &[String], out: &mut dyn Write) -> io::Result<i32> {
    if args.len() != 3 {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "Usage: byond-wire <address> <port> <message>",
        ));
    }
    match topic_raw(&args[0], &args[1], &args[2], Duration::from_secs(5))? {
        RawResponse::Null => Ok(2),
        RawResponse::Text(bytes) => {
            out.write_all(&bytes)?;
            out.flush()?;
            Ok(0)
        }
        RawResponse::Number(value) => {
            write!(out, "{value}")?;
            out.flush()?;
            Ok(0)
        }
    }
}

fn main() {
    let args: Vec<_> = std::env::args().skip(1).collect();
    let code = run(&args, &mut io::stdout().lock()).unwrap_or_else(|error| {
        eprintln!("{error}");
        if matches!(
            error.kind(),
            io::ErrorKind::TimedOut | io::ErrorKind::WouldBlock
        ) {
            124
        } else {
            1
        }
    });
    std::process::exit(code);
}

#[cfg(test)]
#[path = "test-cli.rs"]
mod tests;
