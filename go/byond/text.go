package byond

import (
	"bytes"
	"fmt"
	"strings"
	"unicode/utf8"
)

// DecodeText removes tested BYOND markers and validates each UTF-8 run.
// It preserves HTML and literal Unicode, and does not modify data.
func DecodeText(data []byte) (string, error) {
	var text strings.Builder
	text.Grow(len(data))
	for {
		marker := bytes.IndexByte(data, 255)
		end := len(data)
		if marker >= 0 {
			end = marker
		}
		if !utf8.Valid(data[:end]) {
			return "", fmt.Errorf("invalid UTF-8 text")
		}
		text.Write(data[:end])
		if marker < 0 {
			return text.String(), nil
		}
		if marker+1 == len(data) || strings.IndexByte("\x06\x07\x08\x09\x12\x15\x16\x17\x18\x19\x1f\x20\x21\x22\x23\x24\x25\x26", data[marker+1]) < 0 {
			return "", fmt.Errorf("unknown or truncated BYOND text marker")
		}
		data = data[marker+2:]
	}
}
