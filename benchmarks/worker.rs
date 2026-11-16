#[path = "../rust/byond-wire.rs"]
mod byond;
use std::io::{self, BufRead, Write};
use std::time::{Duration, Instant};
fn main() {
    let args: Vec<String> = std::env::args().collect();
    for line in io::stdin().lock().lines() {
        let line = line.unwrap();
        let fields: Vec<&str> = line.split('\t').collect();
        let start = Instant::now();
        let result = if fields[0] == "raw" {
            byond::topic_raw(&args[1], &args[2], fields[1], Duration::from_secs(5))
                .map(|v| match v { byond::Response::Text(t) => ("text", t.len()), byond::Response::Number(_) => ("number", 4), byond::Response::Null => ("null", 0) })
        } else {
            byond::topic(&args[1], &args[2], fields[1], Duration::from_secs(5))
                .map(|v| match v { byond::Response::Text(t) => ("text", t.len()), byond::Response::Number(_) => ("number", 4), byond::Response::Null => ("null", 0) })
        };
        let ms = start.elapsed().as_secs_f64() * 1000.0;
        match result {
            Ok((kind, size)) => println!("{ms}\t{kind}\t{size}"),
            Err(e) => {
                let kind = if matches!(e.kind(), io::ErrorKind::TimedOut | io::ErrorKind::WouldBlock) { "timeout" } else { "error" };
                println!("{ms}\t{kind}\t{}", e.to_string().replace('\n', " "));
            }
        }
        io::stdout().flush().unwrap();
    }
}
