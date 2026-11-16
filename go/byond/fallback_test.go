package byond

import (
	"context"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"net"
	"syscall"
	"testing"
	"time"
)

// Return two ordered A records, and no AAAA records, without external DNS.
func fallbackDNS(ctx context.Context, _, _ string) (net.Conn, error) {
	client, peer := net.Pipe()
	go func() {
		defer peer.Close()
		if deadline, ok := ctx.Deadline(); ok {
			peer.SetDeadline(deadline)
		}
		var length [2]byte
		if _, err := io.ReadFull(peer, length[:]); err != nil {
			return
		}
		query := make([]byte, binary.BigEndian.Uint16(length[:]))
		if _, err := io.ReadFull(peer, query); err != nil {
			return
		}
		end := 12
		for query[end] != 0 {
			end += int(query[end]) + 1
		}
		end += 5 // Root label, query type, and class.
		reply := append([]byte(nil), query[:end]...)
		copy(reply[2:12], []byte{0x81, 0x80, 0, 1, 0, 0, 0, 0, 0, 0})
		if binary.BigEndian.Uint16(query[end-4:end-2]) == 1 {
			reply[7] = 2
			for _, last := range []byte{2, 1} {
				reply = append(reply, 0xc0, 12, 0, 1, 0, 1, 0, 0, 0, 0, 0, 4, 127, 0, 0, last)
			}
		}
		binary.BigEndian.PutUint16(length[:], uint16(len(reply)))
		peer.Write(append(length[:], reply...))
	}()
	return client, nil
}

func TestAddressFallbackAndCleanup(t *testing.T) {
	// These tests are serial: restore the process-wide resolver after this test.
	previous := net.DefaultResolver
	net.DefaultResolver = &net.Resolver{PreferGo: true, Dial: fallbackDNS}
	t.Cleanup(func() { net.DefaultResolver = previous })
	const host = "byond-fallback.invalid."
	addresses, err := net.LookupHost(host)
	if err != nil || len(addresses) != 2 || addresses[0] != "127.0.0.2" || addresses[1] != "127.0.0.1" {
		t.Fatalf("unexpected fallback order: %v, %v", addresses, err)
	}
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	_, port, _ := net.SplitHostPort(listener.Addr().String())
	if conn, err := net.DialTimeout("tcp", net.JoinHostPort(addresses[0], port), time.Second); err == nil {
		conn.Close()
		t.Fatal("first endpoint unexpectedly accepted a connection")
	} else if !errors.Is(err, syscall.ECONNREFUSED) {
		t.Fatalf("first endpoint was not refused: %v", err)
	}
	done := make(chan error, 1)
	go func() {
		conn, err := listener.Accept()
		if err != nil {
			done <- err
			return
		}
		defer conn.Close()
		conn.SetDeadline(time.Now().Add(time.Second))
		var request [17]byte
		if _, err = io.ReadFull(conn, request[:]); err == nil && string(request[:]) != "\x00\x83\x00\x0d\x00\x00\x00\x00\x00?status\x00" {
			err = fmt.Errorf("incorrect fallback request: %x", request)
		}
		if err == nil {
			_, err = conn.Write([]byte{0, 131, 0, 4, 6, 'o', 'k', 0})
		}
		if err == nil {
			_, err = conn.Read(make([]byte, 1))
			if err == io.EOF {
				err = nil
			} else if err == nil {
				err = fmt.Errorf("unexpected data after request")
			}
		}
		done <- err
	}()
	result, err := Topic(host, port, "status", time.Second)
	if err != nil || result.Kind != Text || result.Text != "ok" {
		t.Fatalf("fallback failed: %+v, %v", result, err)
	}
	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("fallback peer or cleanup failed: %v", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("fallback connection was not closed")
	}
}
