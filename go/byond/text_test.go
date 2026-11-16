package byond_test

import (
	"github.com/Wirewraith/byond-wire/go/byond"
	"bytes"
	"encoding/hex"
	"os"
	"strings"
	"testing"
)

func TestDecodeTextVectors(t *testing.T) {
	vectors, err := os.ReadFile("../../tests/text-vectors.tsv")
	if os.IsNotExist(err) {
		vectors, err = os.ReadFile("testdata/text-vectors.tsv")
	}
	if err != nil {
		t.Fatal(err)
	}
	for _, line := range strings.Split(strings.TrimSuffix(string(vectors), "\n"), "\n") {
		if strings.HasPrefix(line, "#") {
			continue
		}
		fields := strings.Split(line, "\t")
		data, err := hex.DecodeString(fields[1])
		if err != nil {
			t.Fatal(err)
		}
		original := bytes.Clone(data)
		got, err := byond.DecodeText(data)
		if fields[2] == "-" {
			if err == nil {
				t.Errorf("%s: accepted malformed text", fields[0])
			}
		} else {
			expected, errHex := hex.DecodeString(fields[2])
			if errHex != nil {
				t.Fatal(errHex)
			}
			if err != nil || got != string(expected) {
				t.Errorf("%s: got %q, %v", fields[0], got, err)
			}
		}
		if !bytes.Equal(data, original) {
			t.Fatal("mutated input")
		}
	}
	expected := strings.Repeat("x", 65533)
	if got, err := byond.DecodeText([]byte(expected)); err != nil || got != expected {
		t.Fatal(err)
	}
}

var decodedText string

func BenchmarkDecodeText(b *testing.B) {
	for _, size := range []int{280, 65533} {
		name := "typical"
		if size > 280 {
			name = "large"
		}
		for _, formatted := range []bool{false, true} {
			input := bytes.Repeat([]byte{'x'}, size)
			label := name + "/plain"
			if formatted {
				input[0], input[1] = 255, 21
				label = name + "/formatted"
			}
			b.Run(label, func(b *testing.B) {
				b.ReportAllocs()
				for i := 0; i < b.N; i++ {
					value, err := byond.DecodeText(input)
					if err != nil {
						b.Fatal(err)
					}
					decodedText = value
				}
			})
		}
	}
}
