use super::byond::{connect, request, topic_raw as topic, RawResponse as Response};
use super::*;
use std::io::Read;
use std::net::TcpListener;
use std::thread;
use std::time::Instant;

// The peer checks the wire request independently, including its length and prefix.
fn server(reply: Vec<u8>, fragment: bool, delay: Duration) -> (String, thread::JoinHandle<()>) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let port = listener.local_addr().unwrap().port().to_string();
    let handle = thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        stream
            .set_read_timeout(Some(Duration::from_secs(2)))
            .unwrap();
        stream
            .set_write_timeout(Some(Duration::from_secs(2)))
            .unwrap();
        let mut packet = [0; 17];
        stream.read_exact(&mut packet).unwrap();
        assert_eq!(&packet, b"\0\x83\0\x0d\0\0\0\0\0?status\0");
        thread::sleep(delay);
        if fragment {
            for byte in reply {
                if stream.write_all(&[byte]).is_err() {
                    break;
                }
                thread::sleep(Duration::from_millis(1));
            }
        } else {
            let _ = stream.write_all(&reply);
        }
    });
    (port, handle)
}

fn frame(body: &[u8]) -> Vec<u8> {
    let mut result = vec![0, 131, (body.len() >> 8) as u8, body.len() as u8];
    result.extend_from_slice(body);
    result
}

#[test]
fn request_vectors_and_limits() {
    assert_eq!(
        request("status").unwrap(),
        b"\0\x83\0\x0d\0\0\0\0\0?status\0"
    );
    assert_eq!(request("?ping").unwrap(), b"\0\x83\0\x0b\0\0\0\0\0?ping\0");
    assert_eq!(&request("café'\\n").unwrap()[9..], "?café'\\n\0".as_bytes());
    assert_eq!(&request("café'\\n").unwrap()[2..4], &[0, 15]);
    let packet = request(&"x".repeat(65528)).unwrap();
    assert_eq!(packet.len(), 65539);
    assert_eq!(&packet[2..4], &[255, 255]);
    assert_eq!(&packet[9..11], b"?x");
    assert_eq!(packet.last(), Some(&0));
    assert!(request(&"x".repeat(65529)).is_err());
    assert_eq!(request(&format!("?{}", "x".repeat(65528))).unwrap(), packet);
    assert_eq!(&request("").unwrap()[9..], b"?\0");
    assert_eq!(&request("??status").unwrap()[9..], b"??status\0");
    assert!(request("a\0b").is_err());
}

#[test]
fn response_types_and_raw_text() {
    for (body, expected) in [
        (vec![6, b'o', b'k', 0], Response::Text(b"ok".to_vec())),
        (vec![6, 0], Response::Text(vec![])),
        (vec![0], Response::Null),
        (vec![42, 0, 0, 128, 63], Response::Number(1.0)),
        (vec![42, 0, 0, 32, 192], Response::Number(-2.5)),
        (vec![6, 255, 0, b'x', 0], Response::Text(vec![255, 0, b'x'])),
    ] {
        let (port, peer) = server(frame(&body), true, Duration::ZERO);
        assert_eq!(
            topic("127.0.0.1", &port, "status", Duration::from_secs(2)).unwrap(),
            expected
        );
        peer.join().unwrap();
    }
}

#[test]
fn maximum_response() {
    let mut body = vec![6];
    body.extend(vec![b'x'; 65533]);
    body.push(0);
    let (port, peer) = server(frame(&body), false, Duration::ZERO);
    assert_eq!(
        topic("127.0.0.1", &port, "status", Duration::from_secs(2)).unwrap(),
        Response::Text(vec![b'x'; 65533])
    );
    peer.join().unwrap();
}

#[test]
fn rejects_malformed_and_truncated_responses() {
    for reply in [
        vec![],
        vec![0, 131],
        vec![1, 131, 0, 1, 0],
        vec![0, 131, 0, 0],
        vec![0, 131, 0, 4, 6, b'x'],
        frame(&[0, 0]),
        frame(&[6]),
        frame(&[6, b'x']),
        frame(&[42, 0]),
        frame(&[99]),
    ] {
        let (port, peer) = server(reply, false, Duration::ZERO);
        assert!(topic("127.0.0.1", &port, "status", Duration::from_secs(2)).is_err());
        peer.join().unwrap();
    }
}

#[test]
fn validates_arguments_and_connection_errors() {
    for (host, port) in [
        ("", "1"),
        ("localhost", "0"),
        ("localhost", "65536"),
        ("localhost", "no"),
    ] {
        assert!(topic(host, port, "status", Duration::from_secs(1)).is_err());
    }
    assert!(run(&[], &mut Vec::new()).is_err());
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let port = listener.local_addr().unwrap().port().to_string();
    drop(listener);
    assert!(topic("127.0.0.1", &port, "status", Duration::from_secs(1)).is_err());
}

#[test]
fn total_deadline_bounds_silent_and_trickling_peers() {
    for (fragment, delay) in [(false, Duration::from_millis(100)), (true, Duration::ZERO)] {
        let (port, peer) = server(frame(&vec![6; 1000]), fragment, delay);
        let start = Instant::now();
        let error = topic("127.0.0.1", &port, "status", Duration::from_millis(25)).unwrap_err();
        assert!(
            matches!(
                error.kind(),
                io::ErrorKind::TimedOut | io::ErrorKind::WouldBlock
            ),
            "{error}"
        );
        assert!(start.elapsed() < Duration::from_secs(1));
        peer.join().unwrap();
    }
}

#[test]
fn cli_output_null_and_write_errors() {
    for (body, code, expected) in [
        (vec![42, 0, 0, 32, 192], 0, b"-2.5".to_vec()),
        (vec![6, b'x', 0], 0, b"x".to_vec()),
        (vec![6, 0], 0, vec![]),
        (vec![0], 2, vec![]),
    ] {
        let (port, peer) = server(frame(&body), false, Duration::ZERO);
        let mut output = Vec::new();
        assert_eq!(
            run(&["127.0.0.1".into(), port, "status".into()], &mut output).unwrap(),
            code
        );
        assert_eq!(output, expected);
        peer.join().unwrap();
    }
    struct Broken;
    impl Write for Broken {
        fn write(&mut self, _: &[u8]) -> io::Result<usize> {
            Err(io::ErrorKind::BrokenPipe.into())
        }
        fn flush(&mut self) -> io::Result<()> {
            Ok(())
        }
    }
    let (port, peer) = server(frame(&[6, b'x', 0]), false, Duration::ZERO);
    assert!(run(&["127.0.0.1".into(), port, "status".into()], &mut Broken).is_err());
    peer.join().unwrap();
}

#[test]
#[ignore = "manual request construction benchmark"]
fn benchmark_request() {
    for (size, iterations) in [(6, 1_000_000), (65528, 20_000)] {
        let query = "x".repeat(size);
        let start = Instant::now();
        for _ in 0..iterations {
            std::hint::black_box(request(std::hint::black_box(&query)).unwrap());
        }
        println!(
            "query={size} bytes: {:.1} ns/request",
            start.elapsed().as_nanos() as f64 / iterations as f64
        );
    }
}

#[test]
fn reports_output_flush_errors() {
    struct FlushError;
    impl Write for FlushError {
        fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
            Ok(bytes.len())
        }
        fn flush(&mut self) -> io::Result<()> {
            Err(io::ErrorKind::BrokenPipe.into())
        }
    }
    let (port, peer) = server(frame(&[6, b'x', 0]), false, Duration::ZERO);
    assert!(run(
        &["127.0.0.1".into(), port, "status".into()],
        &mut FlushError
    )
    .is_err());
    peer.join().unwrap();
}

#[test]
fn connection_falls_back_and_closes_the_successful_socket() {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    let refused = TcpListener::bind("127.0.0.1:0").unwrap();
    let first = refused.local_addr().unwrap();
    drop(refused);
    let deadline = Instant::now() + Duration::from_secs(1);
    let stream = connect([first, address], deadline).unwrap();
    let (mut peer, _) = listener.accept().unwrap();
    peer.set_read_timeout(Some(Duration::from_secs(1))).unwrap();
    drop(stream);
    assert_eq!(peer.read(&mut [0]).unwrap(), 0);
}

#[test]
fn fallback_preserves_the_original_deadline() {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    let refused = TcpListener::bind("127.0.0.1:0").unwrap();
    let first = refused.local_addr().unwrap();
    drop(refused);
    let deadline = Instant::now() + Duration::from_millis(20);
    let addresses = std::iter::once(first).chain(std::iter::once_with(|| {
        thread::sleep(Duration::from_millis(30));
        address
    }));
    assert_eq!(
        connect(addresses, deadline).unwrap_err().kind(),
        io::ErrorKind::TimedOut
    );
    listener.set_nonblocking(true).unwrap();
    assert_eq!(
        listener.accept().unwrap_err().kind(),
        io::ErrorKind::WouldBlock
    );
}

#[test]
fn connection_errors_preserve_empty_and_exhausted_address_results() {
    let deadline = Instant::now() + Duration::from_secs(1);
    assert_eq!(
        connect([], deadline).unwrap_err().kind(),
        io::ErrorKind::InvalidData
    );
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    drop(listener);
    assert_eq!(
        connect([address, address], deadline).unwrap_err().kind(),
        io::ErrorKind::ConnectionRefused
    );
}
