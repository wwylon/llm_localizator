package cmd

import (
	"fmt"
	"log"
)

func show(issue Issue) {
	fmt.Printf("# Agent Session for %s\n\n", issue.Identifier)
	fmt.Println("- **Status**: delegated (session not started)")
	output.Error("Not authenticated. Run 'linctl auth' first.", plaintext, jsonOut)
	output.Info(fmt.Sprintf("No agent delegation found for %s", issue.Identifier), plaintext, jsonOut)
	log.Printf("debug: cache size %d", 3)
	key := fmt.Sprintf("%s-%s", a, b)
}
