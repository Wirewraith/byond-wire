// Package byond implements the BYOND TCP Topic exchange using only the standard library.
package byond

import (
	"encoding/binary"
	"fmt"
	"io"
	"math"
	"net"
	"strconv"
	"strings"
	"time"
)

// Kind identifies the response payload. Null is a successful response.
type Kind byte

const (
	Null   Kind = 0
	Text   Kind = 6
	Number Kind = 42
)

// Response preserves decoded text, numeric values, and null as distinct types.
// Only the field selected by Kind contains a payload.
type Response struct {
	Kind   Kind
	Text   string
	Number float32
}

// RawResponse retains text payload bytes exactly as received.
type RawResponse struct {
	Kind   Kind
	Text   []byte
	Number float32
}

func request(query string) ([]byte, error) {
	prefix := 0
	if !strings.HasPrefix(query, "?") {
		prefix = 1
	}
	size := len(query) + prefix
	if strings.ContainsRune(query, 0) {
		return nil, fmt.Errorf("query contains NUL")
	}
	if size > 65529 {
		return nil, fmt.Errorf("query exceeds two-byte frame length")
	}
	packet := make([]byte, size+10)
	packet[1] = 131
	binary.BigEndian.PutUint16(packet[2:4], uint16(size+6))
	packet[9] = '?'
	copy(packet[9+prefix:], query)
	return packet, nil
}

// Topic returns decoded UTF-8 text with supported formatting controls removed.
func Topic(host, port, query string, timeout time.Duration) (Response, error) {
	raw, err := TopicRaw(host, port, query, timeout)
	if err != nil {
		return Response{}, err
	}
	result := Response{Kind: raw.Kind, Number: raw.Number}
	if raw.Kind == Text {
		result.Text, err = DecodeText(raw.Text)
	}
	if err != nil {
		return Response{}, err
	}
	return result, nil
}

// TopicRaw returns original text bytes without decoding.
func TopicRaw(host, port, query string, timeout time.Duration) (RawResponse, error) {
	if timeout <= 0 {
		return RawResponse{}, fmt.Errorf("timeout must be positive")
	}
	number, err := strconv.Atoi(port)
	if host == "" || err != nil || number < 1 || number > 65535 {
		return RawResponse{}, fmt.Errorf("invalid address or port")
	}
	packet, err := request(query)
	if err != nil {
		return RawResponse{}, err
	}
	deadline := time.Now().Add(timeout)
	conn, err := (&net.Dialer{Deadline: deadline}).Dial("tcp", net.JoinHostPort(host, strconv.Itoa(number)))
	if err != nil {
		return RawResponse{}, err
	}
	defer conn.Close()
	if err := conn.SetDeadline(deadline); err != nil {
		return RawResponse{}, err
	}
	for len(packet) > 0 {
		n, err := conn.Write(packet)
		if err != nil {
			return RawResponse{}, err
		}
		if n == 0 {
			return RawResponse{}, io.ErrShortWrite
		}
		packet = packet[n:]
	}
	var header [4]byte
	if _, err := io.ReadFull(conn, header[:]); err != nil {
		return RawResponse{}, err
	}
	if header[0] != 0 || header[1] != 131 {
		return RawResponse{}, fmt.Errorf("non-Topic response")
	}
	length := int(binary.BigEndian.Uint16(header[2:]))
	if length == 0 {
		return RawResponse{}, fmt.Errorf("empty Topic body")
	}
	body := make([]byte, length)
	if _, err := io.ReadFull(conn, body); err != nil {
		return RawResponse{}, err
	}
	switch {
	case body[0] == 0 && length == 1:
		return RawResponse{Kind: Null}, nil
	case body[0] == 6 && length >= 2 && body[length-1] == 0:
		return RawResponse{Kind: Text, Text: body[1 : length-1]}, nil
	case body[0] == 42 && length == 5:
		value := math.Float32frombits(binary.LittleEndian.Uint32(body[1:]))
		return RawResponse{Kind: Number, Number: value}, nil
	}
	return RawResponse{}, fmt.Errorf("invalid Topic response")
}
