use byond_wire::{topic, topic_raw, RawResponse, Response};
use std::io::{Read, Write};
use std::net::TcpListener;
use std::thread;
use std::time::Duration;

fn server(body: Vec<u8>) -> (String, thread::JoinHandle<()>) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let port = listener.local_addr().unwrap().port().to_string();
    let peer = thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        stream
            .set_read_timeout(Some(Duration::from_secs(2)))
            .unwrap();
        let mut request = [0; 17];
        stream.read_exact(&mut request).unwrap();
        assert_eq!(&request, b"\0\x83\0\x0d\0\0\0\0\0?status\0");
        let mut reply = vec![0, 131, 0, body.len() as u8];
        reply.extend(body);
        stream.write_all(&reply).unwrap();
        assert_eq!(
            stream.read(&mut [0]).unwrap(),
            0,
            "client left its socket open"
        );
    });
    (port, peer)
}

#[test]
fn imported_raw_topic_preserves_types() {
    for (body, expected) in [
        (vec![0], RawResponse::Null),
        (vec![6, 0], RawResponse::Text(vec![])),
        (vec![6, 255, 0], RawResponse::Text(vec![255])),
        (vec![42, 0, 0, 32, 192], RawResponse::Number(-2.5)),
    ] {
        let (port, peer) = server(body);
        assert_eq!(
            topic_raw("127.0.0.1", &port, "status", Duration::from_secs(2)).unwrap(),
            expected
        );
        peer.join().unwrap();
    }
}

#[test]
fn default_topic_returns_strings_and_native_types() {
    for (body, expected) in [
        (
            vec![6, 255, 22, b'c', b'a', b'f', 195, 169, 0],
            Response::Text("café".to_owned()),
        ),
        (vec![6, 0], Response::Text(String::new())),
        (
            vec![6, 239, 187, 191, b'a', 0, 240, 159, 153, 130, 0],
            Response::Text("\u{feff}a\0🙂".to_owned()),
        ),
        (vec![0], Response::Null),
        (vec![42, 0, 0, 32, 192], Response::Number(-2.5)),
    ] {
        let (port, peer) = server(body);
        assert_eq!(
            topic("127.0.0.1", &port, "status", Duration::from_secs(2)).unwrap(),
            expected
        );
        peer.join().unwrap();
    }
    for bytes in [vec![195], vec![255], vec![255, 27], vec![195, 255, 21, 169]] {
        let mut body = vec![6];
        body.extend(bytes);
        body.push(0);
        let (port, peer) = server(body);
        assert!(topic("127.0.0.1", &port, "status", Duration::from_secs(2)).is_err());
        peer.join().unwrap();
    }
}

#[test]
fn overflowing_timeout_returns_an_error() {
    assert_eq!(
        topic("127.0.0.1", "1", "status", Duration::MAX)
            .unwrap_err()
            .kind(),
        std::io::ErrorKind::InvalidInput
    );
    assert_eq!(
        topic_raw("127.0.0.1", "1", "status", Duration::MAX)
            .unwrap_err()
            .kind(),
        std::io::ErrorKind::InvalidInput
    );
}

#[test]
fn zero_timeout_is_rejected_before_resolution() {
    for host in ["127.0.0.1", "invalid host"] {
        for error in [
            topic(host, "1", "status", Duration::ZERO).unwrap_err(),
            topic_raw(host, "1", "status", Duration::ZERO).unwrap_err(),
        ] {
            assert_eq!(
                error.kind(),
                std::io::ErrorKind::InvalidInput,
                "zero timeout reached networking for {host:?}"
            );
        }
    }
}
