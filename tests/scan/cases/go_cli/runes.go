package main

import "fmt"

func quote(c rune) bool {
	if c == '"' || c == '\'' {
		return true
	}
	return false
}

func main() {
	fmt.Println("Please choose a file to open")
}
