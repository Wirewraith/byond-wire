// Standard library only. Exit: 0 value, 1 error, 2 null, 124 network timeout.
use std::io::{self, Read, Write};
use std::net::{SocketAddr, TcpStream, ToSocketAddrs};
use std::time::{Duration, Instant};

/// Remove tested BYOND markers and strictly decode UTF-8, preserving HTML.
pub fn decode_text(data: &[u8]) -> io::Result<String> {
    if let Ok(text) = std::str::from_utf8(data) {
        return Ok(text.to_owned());
    }
    let mut parts = data.split(|&byte| byte == 255);
    let mut text = String::with_capacity(data.len());
    text.push_str(
        std::str::from_utf8(parts.next().unwrap())
            .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?,
    );
    for part in parts {
        if part.is_empty()
            || !b"\x06\x07\x08\x09\x12\x15\x16\x17\x18\x19\x1f\x20\x21\x22\x23\x24\x25\x26"
                .contains(&part[0])
        {
            return Err(invalid("unknown or truncated BYOND text marker"));
        }
        text.push_str(
            std::str::from_utf8(&part[1..])
                .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?,
        );
    }
    Ok(text)
}

fn invalid(message: &str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message)
}

/// A complete Topic response. Text is decoded by default.
#[derive(Debug, PartialEq)]
pub enum Response<T = String> {
    Null,
    Text(T),
    Number(f32),
}

/// A complete response retaining the original text bytes.
pub type RawResponse = Response<Vec<u8>>;

pub(crate) fn request(query: &str) -> io::Result<Vec<u8>> {
    let prefix = usize::from(!query.starts_with('?'));
    let size = query.len() + prefix;
    if query.as_bytes().contains(&0) || size > 65529 {
        return Err(invalid(
            "query contains NUL or exceeds two-byte frame length",
        ));
    }
    let mut packet = vec![0; size + 10];
    packet[1] = 131;
    packet[2..4].copy_from_slice(&((size + 6) as u16).to_be_bytes());
    packet[9] = b'?';
    packet[9 + prefix..9 + size].copy_from_slice(query.as_bytes());
    Ok(packet)
}

fn remaining(deadline: Instant) -> io::Result<Duration> {
    deadline
        .checked_duration_since(Instant::now())
        .filter(|duration| !duration.is_zero())
        .ok_or_else(|| io::ErrorKind::TimedOut.into())
}

// Reset the timeout before each operation so trickled bytes cannot extend the deadline.
fn transfer(
    stream: &mut TcpStream,
    mut bytes: &mut [u8],
    deadline: Instant,
    sending: bool,
) -> io::Result<()> {
    while !bytes.is_empty() {
        let timeout = Some(remaining(deadline)?);
        let result = if sending {
            stream.set_write_timeout(timeout)?;
            stream.write(bytes)
        } else {
            stream.set_read_timeout(timeout)?;
            stream.read(bytes)
        };
        match result {
            Ok(0) => return Err(invalid("connection closed before frame was complete")),
            Ok(count) => bytes = &mut bytes[count..],
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(error) => return Err(error),
        }
    }
    Ok(())
}

/// Return decoded text, preserving numeric and null results.
pub fn topic(host: &str, port: &str, query: &str, timeout: Duration) -> io::Result<Response> {
    match topic_raw(host, port, query, timeout)? {
        Response::Text(bytes) => {
            let text = if bytes.contains(&255) {
                decode_text(&bytes)?
            } else {
                String::from_utf8(bytes)
                    .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?
            };
            Ok(Response::Text(text))
        }
        Response::Number(value) => Ok(Response::Number(value)),
        Response::Null => Ok(Response::Null),
    }
}

/// Return the original text bytes without decoding.
pub fn topic_raw(
    host: &str,
    port: &str,
    query: &str,
    timeout: Duration,
) -> io::Result<RawResponse> {
    let port = port.parse::<u16>().ok().filter(|&port| port != 0);
    let port = port
        .filter(|_| !host.is_empty())
        .ok_or_else(|| invalid("invalid address or port"))?;
    let deadline = Instant::now()
        .checked_add(timeout)
        .filter(|_| !timeout.is_zero())
        .ok_or_else(|| {
            io::Error::new(
                io::ErrorKind::InvalidInput,
                "timeout must be positive and within supported range",
            )
        })?;
    let mut packet = request(query)?;
    // Standard-library hostname resolution uses the operating system's DNS timeout.
    let mut stream = connect((host, port).to_socket_addrs()?, deadline)?;
    transfer(&mut stream, &mut packet, deadline, true)?;
    let mut header = [0; 4];
    transfer(&mut stream, &mut header, deadline, false)?;
    if header[..2] != [0, 131] {
        return Err(invalid("non-Topic response"));
    }
    let mut body = vec![0; u16::from_be_bytes([header[2], header[3]]) as usize];
    transfer(&mut stream, &mut body, deadline, false)?;
    match body.as_slice() {
        [0] => Ok(Response::Null),
        [6, .., 0] => {
            let length = body.len() - 2;
            body.copy_within(1..length + 1, 0);
            body.truncate(length);
            Ok(Response::Text(body))
        }
        [42, a, b, c, d] => Ok(Response::Number(f32::from_le_bytes([*a, *b, *c, *d]))),
        _ => Err(invalid("invalid Topic response")),
    }
}

pub(crate) fn connect(
    addresses: impl IntoIterator<Item = SocketAddr>,
    deadline: Instant,
) -> io::Result<TcpStream> {
    let mut error = None;
    for address in addresses {
        match TcpStream::connect_timeout(&address, remaining(deadline)?) {
            Ok(stream) => return Ok(stream),
            Err(failure) => error = Some(failure),
        }
    }
    Err(error.unwrap_or_else(|| invalid("address resolved to no endpoints")))
}
