package main

import (
	"bufio"
	"github.com/Wirewraith/byond-wire/go/byond"
	"fmt"
	"os"
	"strings"
	"time"
)

func main() {
	scanner := bufio.NewScanner(os.Stdin)
	for scanner.Scan() {
		fields := strings.Split(scanner.Text(), "\t")
		start := time.Now()
		kind, size := byond.Null, 0
		var err error
		if fields[0] == "raw" {
			var value byond.RawResponse
			value, err = byond.TopicRaw(os.Args[1], os.Args[2], fields[1], 5*time.Second)
			kind, size = value.Kind, len(value.Text)
		} else {
			var value byond.Response
			value, err = byond.Topic(os.Args[1], os.Args[2], fields[1], 5*time.Second)
			kind, size = value.Kind, len(value.Text)
		}
		ms := float64(time.Since(start)) / 1e6
		if err != nil {
			fmt.Printf("%f\terror\t%s\n", ms, strings.ReplaceAll(err.Error(), "\n", " "))
			continue
		}
		name := "text"
		if kind == byond.Null {
			name = "null"
			size = 0
		}
		if kind == byond.Number {
			name = "number"
			size = 4
		}
		fmt.Printf("%f\t%s\t%d\n", ms, name, size)
	}
}
