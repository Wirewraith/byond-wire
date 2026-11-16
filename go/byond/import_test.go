package byond_test

import (
	"github.com/Wirewraith/byond-wire/go/byond"
	"io"
	"net"
	"strings"
	"testing"
	"time"
)

func TestImportedTopic(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
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
		if _, err = io.ReadFull(conn, request[:]); err == nil {
			_, err = conn.Write([]byte{0, 131, 0, 5, 42, 0, 0, 32, 192})
		}
		done <- err
	}()
	host, port, _ := net.SplitHostPort(listener.Addr().String())
	response, err := byond.Topic(host, port, "status", time.Second)
	if err != nil || response.Kind != byond.Number || response.Number != -2.5 {
		t.Fatalf("got %+v, %v", response, err)
	}
	if err := <-done; err != nil {
		t.Fatal(err)
	}
}

func TestDefaultTopicStrings(t *testing.T) {
	for _, tc := range []struct {
		body    []byte
		kind    byond.Kind
		text    string
		number  float32
		invalid bool
	}{
		{[]byte{6, 255, 22, 'c', 'a', 'f', 195, 169, 0}, byond.Text, "café", 0, false},
		{[]byte{6, 0}, byond.Text, "", 0, false},
		{[]byte{0}, byond.Null, "", 0, false},
		{[]byte{42, 0, 0, 32, 192}, byond.Number, "", -2.5, false},
		{[]byte{6, 255, 0}, byond.Text, "", 0, true},
		{[]byte{6, 195, 255, 21, 169, 0}, byond.Text, "", 0, true},
	} {
		listener, err := net.Listen("tcp", "127.0.0.1:0")
		if err != nil {
			t.Fatal(err)
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
			if _, err = io.ReadFull(conn, request[:]); err == nil {
				reply := append([]byte{0, 131, 0, byte(len(tc.body))}, tc.body...)
				_, err = conn.Write(reply)
			}
			done <- err
		}()
		host, port, _ := net.SplitHostPort(listener.Addr().String())
		result, err := byond.Topic(host, port, "status", time.Second)
		listener.Close()
		if peerErr := <-done; peerErr != nil {
			t.Fatal(peerErr)
		}
		if tc.invalid {
			if err == nil {
				t.Fatal("malformed text accepted")
			}
		} else if err != nil || result.Kind != tc.kind || strings.Compare(result.Text, tc.text) != 0 || result.Number != tc.number {
			t.Fatalf("got %+v, %v", result, err)
		}
	}
}
