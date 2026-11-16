package main

import (
	"bytes"
	"encoding/binary"
	"io"
	"net"
	"testing"
	"time"
)

func server(t testing.TB, query string, reply []byte, fragment bool, delay time.Duration) (string, string) {
	t.Helper()
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { listener.Close() })
	go func() {
		conn, err := listener.Accept()
		if err != nil {
			return
		}
		defer conn.Close()
		conn.SetDeadline(time.Now().Add(time.Second))
		header := make([]byte, 4)
		if _, err := io.ReadFull(conn, header); err != nil {
			t.Error(err)
			return
		}
		body := make([]byte, int(binary.BigEndian.Uint16(header[2:])))
		if _, err := io.ReadFull(conn, body); err != nil {
			t.Error(err)
			return
		}
		expected := append([]byte{0, 0, 0, 0, 0}, []byte(query)...)
		expected = append(expected, 0)
		if !bytes.Equal(header[:2], []byte{0, 131}) || !bytes.Equal(body, expected) {
			t.Errorf("incorrect request: %x %x", header, body)
		}
		time.Sleep(delay)
		if fragment {
			for _, b := range reply {
				if _, err := conn.Write([]byte{b}); err != nil {
					return
				}
			}
		} else {
			conn.Write(reply)
		}
	}()
	host, port, _ := net.SplitHostPort(listener.Addr().String())
	return host, port
}

func frame(body []byte) []byte {
	return append([]byte{0, 131, byte(len(body) >> 8), byte(len(body))}, body...)
}

func TestCLI(t *testing.T) {
	for _, tc := range []struct {
		body   []byte
		code   int
		output string
	}{
		{[]byte{42, 0, 0, 32, 192}, 0, "-2.5"}, {[]byte{6, 'o', 'k', 0}, 0, "ok"}, {[]byte{6, 0}, 0, ""}, {[]byte{0}, 2, ""}, {[]byte{99}, 1, ""},
	} {
		host, port := server(t, "?status", frame(tc.body), false, 0)
		var out, errors bytes.Buffer
		if code := run([]string{host, port, "status"}, &out, &errors); code != tc.code || out.String() != tc.output || (errors.Len() > 0) != (code == 1) {
			t.Fatalf("code=%d out=%q error=%q", code, out.String(), errors.String())
		}
	}
	var out, errors bytes.Buffer
	if run(nil, &out, &errors) != 1 || errors.Len() == 0 {
		t.Fatal("missing usage error")
	}
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	host, port, _ := net.SplitHostPort(listener.Addr().String())
	listener.Close()
	if run([]string{host, port, "status"}, &out, &errors) != 1 {
		t.Fatal("connection refusal accepted")
	}
}

type failedWriter struct{}

func (failedWriter) Write(p []byte) (int, error) { return 0, io.ErrClosedPipe }
func TestOutputError(t *testing.T) {
	host, port := server(t, "?status", frame([]byte{6, 'x', 0}), false, 0)
	var errors bytes.Buffer
	if run([]string{host, port, "status"}, failedWriter{}, &errors) != 1 {
		t.Fatal("output error accepted")
	}
}
