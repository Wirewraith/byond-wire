// Standard library only. Exit: 0 value, 1 error, 2 null, 124 network timeout.
package main

import (
	"github.com/Wirewraith/byond-wire/go/byond"
	"fmt"
	"io"
	"net"
	"os"
	"strconv"
	"time"
)

func run(args []string, out, errors io.Writer) int {
	if len(args) != 3 {
		fmt.Fprintln(errors, "Usage: byond-wire <address> <port> <message>")
		return 1
	}
	result, err := byond.TopicRaw(args[0], args[1], args[2], 5*time.Second)
	if err != nil {
		fmt.Fprintln(errors, err)
		if timeout, ok := err.(net.Error); ok && timeout.Timeout() {
			return 124
		}
		return 1
	}
	if result.Kind == byond.Null {
		return 2
	}
	output := result.Text
	if result.Kind == byond.Number {
		output = strconv.AppendFloat(nil, float64(result.Number), 'g', -1, 32)
	}
	if n, err := out.Write(output); err != nil || n != len(output) {
		fmt.Fprintln(errors, "failed to write response")
		return 1
	}
	return 0
}

func main() { os.Exit(run(os.Args[1:], os.Stdout, os.Stderr)) }
