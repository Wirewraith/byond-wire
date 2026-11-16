use byond_wire::decode_text;
fn unhex(hex: &str) -> Vec<u8> {
    hex.as_bytes()
        .chunks_exact(2)
        .map(|pair| u8::from_str_radix(std::str::from_utf8(pair).unwrap(), 16).unwrap())
        .collect()
}
#[test]
fn captured_macro_and_malformed_vectors() {
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"));
    let vectors = std::fs::read_to_string(root.join("../tests/text-vectors.tsv"))
        .or_else(|_| std::fs::read_to_string(root.join("tests/text-vectors.tsv")))
        .unwrap();
    for line in vectors
        .lines()
        .filter(|line| !line.starts_with('#'))
    {
        let fields: Vec<_> = line.split('\t').collect();
        let data = unhex(fields[1]);
        let result = decode_text(&data);
        if fields[2] == "-" {
            assert!(result.is_err(), "{}", fields[0]);
        } else {
            assert_eq!(
                result.unwrap().as_bytes(),
                unhex(fields[2]),
                "{}",
                fields[0]
            );
        }
    }
    assert_eq!(decode_text(&vec![b'x'; 65533]).unwrap(), "x".repeat(65533));
}

#[test]
#[ignore = "manual text-decoder benchmark"]
fn benchmark_decode_text() {
    for (size, iterations) in [(280, 100_000), (65533, 2_000)] {
        for formatted in [false, true] {
            let mut input = vec![b'x'; size];
            if formatted {
                input[..2].copy_from_slice(&[255, 21]);
            }
            let start = std::time::Instant::now();
            for _ in 0..iterations {
                std::hint::black_box(decode_text(std::hint::black_box(&input)).unwrap());
            }
            println!(
                "bytes={size} formatted={formatted}: {:.1} ns/call",
                start.elapsed().as_nanos() as f64 / iterations as f64
            );
        }
    }
}
