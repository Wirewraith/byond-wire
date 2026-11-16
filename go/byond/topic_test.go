package byond

import (
	"bytes"
	"encoding/binary"
	"fmt"
	"io"
	"net"
	"strconv"
	"strings"
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

func TestPublicRawResponseTypes(t *testing.T) {
	for _, tc := range []struct {
		body   []byte
		kind   Kind
		text   []byte
		number float32
	}{
		{[]byte{0}, Null, nil, 0}, {[]byte{6, 0}, Text, []byte{}, 0},
		{[]byte{6, 255, 0}, Text, []byte{255}, 0},
		{[]byte{42, 0, 0, 32, 192}, Number, nil, -2.5},
	} {
		host, port := server(t, "?status", frame(tc.body), true, 0)
		result, err := TopicRaw(host, port, "status", time.Second)
		if err != nil || result.Kind != tc.kind || !bytes.Equal(result.Text, tc.text) || result.Number != tc.number {
			t.Fatalf("got %+v, %v", result, err)
		}
	}
}

func TestTopicRaw(t *testing.T) {
	for _, tc := range []struct {
		name, query string
		body        []byte
		want        string
		null        bool
	}{
		{"text", "status", []byte{6, 'o', 'k', 0}, "ok", false},
		{"empty", "?who", []byte{6, 0}, "", false},
		{"null", "playing", []byte{0}, "", true},
		{"number", "ping", []byte{42, 0, 0, 128, 63}, "1", false},
		{"negative fraction", "ping", []byte{42, 0, 0, 32, 192}, "-2.5", false},
		{"literal UTF8", "café'\\n", []byte{6, 255, 0, 'x', 0}, string([]byte{255, 0, 'x'}), false},
		{"large", strings.Repeat("x", 65528), append(append([]byte{6}, bytes.Repeat([]byte{'a'}, 65533)...), 0), strings.Repeat("a", 65533), false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			query := tc.query
			if !strings.HasPrefix(query, "?") {
				query = "?" + query
			}
			host, port := server(t, query, frame(tc.body), tc.name != "large", 0)
			got, err := TopicRaw(host, port, tc.query, time.Second)
			value := string(got.Text)
			if got.Kind == Number {
				value = strconv.FormatFloat(float64(got.Number), 'g', -1, 32)
			}
			if err != nil || value != tc.want || (got.Kind == Null) != tc.null {
				t.Fatalf("got %q, %v; null=%v", value, err, got.Kind == Null)
			}
		})
	}
}

func TestInvalidReplies(t *testing.T) {
	for _, reply := range [][]byte{
		{}, {0, 131}, {1, 131, 0, 1, 0}, {0, 131, 0, 0}, {0, 131, 0, 4, 6, 'x'},
		frame([]byte{0, 0}), frame([]byte{6}), frame([]byte{6, 'x'}), frame([]byte{42, 0}), frame([]byte{99}),
	} {
		host, port := server(t, "?status", reply, false, 0)
		if _, err := TopicRaw(host, port, "status", time.Second); err == nil {
			t.Errorf("accepted %x", reply)
		}
	}
}

func TestValidation(t *testing.T) {
	for _, args := range [][3]string{{"", "1", "status"}, {"localhost", "0", "status"}, {"localhost", "65536", "status"}, {"localhost", "no", "status"}, {"localhost", "1", "a\x00b"}, {"localhost", "1", strings.Repeat("x", 65529)}} {
		if _, err := TopicRaw(args[0], args[1], args[2], time.Second); err == nil {
			t.Errorf("accepted %q", args)
		}
	}
}

func TestTimeout(t *testing.T) {
	host, port := server(t, "?status", frame([]byte{0}), false, 100*time.Millisecond)
	start := time.Now()
	_, err := TopicRaw(host, port, "status", 20*time.Millisecond)
	timeout, ok := err.(net.Error)
	if !ok || !timeout.Timeout() || time.Since(start) > time.Second {
		t.Fatalf("expected bounded timeout, got %v", err)
	}
}

func TestInvalidTimeoutBeforeResolution(t *testing.T) {
	for _, host := range []string{"127.0.0.1", "invalid host"} {
		for _, timeout := range []time.Duration{0, -time.Second} {
			_, err := TopicRaw(host, "1", "status", timeout)
			if err == nil {
				t.Fatalf("accepted timeout %v", timeout)
			}
			if _, network := err.(net.Error); network {
				t.Errorf("timeout %v reached networking: %v", timeout, err)
			}
		}
	}
}

func TestTrickleDeadline(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	done := make(chan struct{})
	go func() {
		defer close(done)
		conn, err := listener.Accept()
		if err != nil {
			return
		}
		defer conn.Close()
		conn.SetDeadline(time.Now().Add(time.Second))
		if _, err := io.ReadFull(conn, make([]byte, 17)); err != nil {
			return
		}
		for _, b := range frame(append([]byte{6}, make([]byte, 100)...)) {
			if _, err := conn.Write([]byte{b}); err != nil {
				return
			}
			time.Sleep(10 * time.Millisecond)
		}
	}()
	host, port, _ := net.SplitHostPort(listener.Addr().String())
	start := time.Now()
	_, err = TopicRaw(host, port, "status", 40*time.Millisecond)
	if timeout, ok := err.(net.Error); !ok || !timeout.Timeout() || time.Since(start) > 300*time.Millisecond {
		t.Fatalf("trickled response extended deadline: %v", err)
	}
	<-done
}

func TestConnectionCleanup(t *testing.T) {
	for _, reply := range [][]byte{frame([]byte{0}), frame([]byte{99}), frame([]byte{6, 255, 0}), nil} {
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
			if _, err = io.ReadFull(conn, make([]byte, 17)); err == nil {
				_, err = conn.Write(reply)
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
		host, port, _ := net.SplitHostPort(listener.Addr().String())
		Topic(host, port, "status", 100*time.Millisecond)
		select {
		case err = <-done:
		case <-time.After(2 * time.Second):
			err = fmt.Errorf("peer did not finish")
		}
		listener.Close()
		if err != nil {
			t.Fatalf("client did not close connection for reply %x: %v", reply, err)
		}
	}
}

func TestLargeRequestUsesOneAllocation(t *testing.T) {
	query := strings.Repeat("x", 65528)
	allocs := testing.AllocsPerRun(100, func() {
		var err error
		benchPacket, err = request(query)
		if err != nil {
			t.Fatal(err)
		}
	})
	if allocs > 1 {
		t.Fatalf("request allocated %.0f times; want one packet allocation", allocs)
	}
}

func BenchmarkRequest(b *testing.B) {
	for _, size := range []int{6, 65528} {
		name := "typical"
		if size > 6 {
			name = "large"
		}
		for _, prefix := range []string{"", "?"} {
			query := prefix + strings.Repeat("x", size)
			b.Run(name+"/prefix="+prefix, func(b *testing.B) {
				b.ReportAllocs()
				for i := 0; i < b.N; i++ {
					packet, err := request(query)
					if err != nil {
						b.Fatal(err)
					}
					benchPacket = packet
				}
			})
		}
	}
}

var benchPacket []byte
