package cmd

import (
	"github.com/spf13/cobra"
	"github.com/spf13/pflag"
)

var downloadCmd = &cobra.Command{
	Use:     "download",
	Aliases: []string{"d"},
	Short:   "Download an exercise.",
	Long: `Download an exercise.

You may download an exercise to work on. If you've already
started working on it, the command will also download your
latest solution.
`,
	Example: `  tool download --exercise=hello-world`,
}

func setupDownloadFlags(flags *pflag.FlagSet) {
	flags.StringP("uuid", "u", "", "the solution UUID")
	flags.BoolP("force", "F", false, "overwrite existing exercise directory")
	cmd.Flags().String("track", "", "the track to download from")
}

var app = &cli.App{
	Name:  "greet",
	Usage: "fight the loneliness!",
	Flags: []cli.Flag{
		&cli.StringFlag{Name: "lang", Value: "english", Usage: "language for the greeting"},
	},
}
