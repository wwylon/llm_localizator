"""Developer-only code around literals is not reported (Swift, Kotlin, Java)."""

from __future__ import annotations

from pathlib import Path

from llm_localizator.scan import build_scanner


def _scan(tmp_path: Path, rel: str, body: str) -> list:
    path = tmp_path / "src" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return build_scanner("source", tmp_path, ["src"]).scan().hardcoded


def _texts(hits) -> set[str]:
    return {" ".join(h.text.split()) for h in hits}


def test_swift_dev_strings(tmp_path: Path) -> None:
    hits = _scan(tmp_path, "View.swift", (
        'struct V: View {\n'
        '    var body: some View {\n'
        '        Text("Search your photo library")\n'
        '        Text("\\(NSLocalizedString("Routed text here", comment: "A longer translator comment")) \\(count) items")\n'
        '        Button("Delete everything now") {}\n'
        '        Menu("More actions") { }\n'
        '            .help("Show more actions")\n'
        '    }\n'
        '}\n'
        'enum Format: String {\n'
        '    case hex = "Hex Colour"\n'
        '}\n'
        '#Preview {\n'
        '    Text("Preview only sample text")\n'
        '}\n'
    ))
    texts = _texts(hits)
    assert {"Search your photo library", "Delete everything now", "More actions", "Show more actions"} <= texts
    assert not any("Routed text here" in t or "translator comment" in t or "NSLocalizedString" in t for t in texts)
    assert "Hex Colour" not in texts
    assert "Preview only sample text" not in texts


def test_swift_escaped_newline_is_whitespace(tmp_path: Path) -> None:
    hits = _scan(tmp_path, "Help.swift", 'Text("First paragraph of help.\\n\\nSecond paragraph of help.")\n')
    assert any(" ".join(h.text.split()) == "First paragraph of help. Second paragraph of help." for h in hits)


def test_kotlin_preview_annotation_and_tests(tmp_path: Path) -> None:
    hits = _scan(tmp_path, "main/Screen.kt", (
        '@Composable\n'
        'fun Screen() { Text("Welcome back to the app") }\n'
        '@Preview\n'
        '@Composable\n'
        'fun ScreenPreview() { Text("Sample preview content here") }\n'
        '@Query("SELECT * FROM items WHERE position > :from ORDER BY position")\n'
        'fun items(): List<Item>\n'
    ))
    texts = _texts(hits)
    assert "Welcome back to the app" in texts
    assert "Sample preview content here" not in texts
    assert not any("SELECT" in t for t in texts)
    hits = _scan(tmp_path, "commonTest/ScreenTest.kt", 'fun t() { Text("Task title for the test fixture") }\n')
    assert not any(h.file.endswith("ScreenTest.kt") for h in hits)


def test_java_wrapped_log_calls_and_constants(tmp_path: Path) -> None:
    hits = _scan(tmp_path, "Service.java", (
        'class S {\n'
        '    public static final String ACTION_HANDLE_START = "action_handle_start";\n'
        '    void run() {\n'
        '        Log.d(TAG, "Client " + id +\n'
        '              " was not added or is already removed");\n'
        '        Toast.makeText(ctx, "Connection lost, please retry", Toast.LENGTH_SHORT).show();\n'
        '    }\n'
        '}\n'
    ))
    texts = _texts(hits)
    assert "Connection lost, please retry" in texts
    assert not any("action_handle_start" in t or "was not added" in t for t in texts)


def test_kotlin_animation_labels_and_named_previews(tmp_path: Path) -> None:
    hits = _scan(tmp_path, "main/Card.kt", (
        'fun Card() {\n'
        '    val alpha by animateFloatAsState(1f, label = "Card alpha animation")\n'
        '    Text("Your card is ready to use")\n'
        '}\n'
        'fun CardPreviewContent() {\n'
        '    Text("Sample preview content here")\n'
        '}\n'
        'fun notify(b: Builder) { b.setContentTitle("Download finished") }\n'
    ))
    texts = _texts(hits)
    assert {"Your card is ready to use", "Download finished"} <= texts
    assert "Card alpha animation" not in texts
    assert "Sample preview content here" not in texts
    hits = _scan(tmp_path, "sampledata/Mock.kt", 'val mock = """Playlist with some mock description"""\n')
    assert not any(h.file.endswith("Mock.kt") for h in hits)


def test_dart_keyword_constants_and_rust_dev_text(tmp_path: Path) -> None:
    hits = _scan(tmp_path, "filters.dart", (
        "class F {\n"
        "  static const String base = 'base';\n"
        "  static const String committer = 'committer-email';\n"
        "  static const String saveLabel = 'Save the draft now';\n"
        "}\n"
    ))
    texts = _texts(hits)
    assert "base" not in texts
    hits = _scan(tmp_path, "main.rs", (
        "use clap::Parser;\n"
        "struct Cli {\n"
        "    /// Show every host in the list\n"
        "    #[arg(short, long)]\n"
        "    all: bool,\n"
        "}\n"
        "fn f<'a>(x: &'a str) -> &'a str { x }\n"
        "fn g() {\n"
        '    let v = parse().expect("Failed to parse the configuration file");\n'
        '    println!("Connection established successfully");\n'
        "}\n"
    ))
    texts = _texts(hits)
    assert "Show every host in the list" in texts
    assert "Connection established successfully" in texts
    assert "Failed to parse the configuration file" not in texts
    assert not any("IntoIterator" in t or t.startswith("a, ") for t in texts)


def test_csharp_message_properties_and_swift_named_arguments(tmp_path: Path) -> None:
    hits = _scan(tmp_path, "Vm.cs", (
        'var box = new MessageBoxViewModel {\n'
        '    Title = "Delete selected files",\n'
        '    Message = "This cannot be undone",\n'
        '    OKButtonContent = "Delete now",\n'
        '};\n'
        'SetBusy("Searching for duplicates");\n'
    ))
    texts = _texts(hits)
    assert {"Delete selected files", "This cannot be undone", "Delete now", "Searching for duplicates"} <= texts
    hits = _scan(tmp_path, "Alert.swift", (
        'alert.showModal(title: "Unable to open file", message: "Choose another document", buttonTitles: ["Close"])\n'
    ))
    texts = _texts(hits)
    assert {"Unable to open file", "Choose another document"} <= texts


def test_inline_markup_message_is_one_hit_in_kotlin_and_swift(tmp_path: Path) -> None:
    hits = _scan(tmp_path, "Msg.kt", 'val m = "You can change this under <link>Edit profile > Settings</link> at any time"\n')
    texts = _texts(hits)
    assert any("You can change this under" in t and "<link>" in t for t in texts)
    hits = _scan(tmp_path, "Msg.swift", 'Text("Visit <b>the help page</b> to learn more about sharing")\n')
    assert any("Visit" in t and "<b>" in t for t in _texts(hits))
    hits = _scan(tmp_path, "Page.kt", 'val page = "<div class=x><p>Welcome back to your dashboard</p></div>"\n')
    assert any("Welcome back to your dashboard" in t for t in _texts(hits))


def test_short_labels_at_ui_sinks_and_simple_holes_in_js_messages(tmp_path: Path) -> None:
    hits = _scan(tmp_path, "A.kt", 'fun f() { Toast.makeText(ctx, "Ad", Toast.LENGTH_SHORT).show() }\n')
    assert "Ad" in _texts(hits)
    hits = _scan(tmp_path, "b.py", 'flash("PM")\nflash("IPv4")\n')
    assert {"PM", "IPv4"} <= _texts(hits)
    hits = _scan(tmp_path, "c.js", 'alert("Search for \\"{q}\\"");\nconst s = "{a} {b}";\n')
    texts = _texts(hits)
    assert any("Search for" in t for t in texts)
    assert "{a} {b}" not in texts


def test_go_struct_tags_and_python_ui_keywords(tmp_path: Path) -> None:
    hits = _scan(tmp_path, "cmd.go", (
        "type Options struct {\n"
        '    Path string `help:"Directory to search for files" default:"auto"`\n'
        '    Prompt string `default:"Type something..." group:"Style Flags"`\n'
        "}\n"
    ))
    texts = _texts(hits)
    assert {"Directory to search for files", "Type something...", "Style Flags"} <= texts
    assert "auto" not in texts
    hits = _scan(tmp_path, "models.py", (
        "class Page(Model):\n"
        '    title = CharField(verbose_name="Page title", help_text="Shown at the top of the page")\n'
        '    slug = SlugField(max_length=80, db_column="page_slug")\n'
        "@app_commands.describe(query=\"Song name or link to play\")\n"
        "async def play(): pass\n"
    ))
    texts = _texts(hits)
    assert {"Page title", "Shown at the top of the page", "Song name or link to play"} <= texts
    assert "page_slug" not in texts


def test_project_translate_wrappers_from_config(tmp_path: Path) -> None:
    from llm_localizator.scan import build_scanner

    src = tmp_path / "src"
    src.mkdir()
    (src / "App.java").write_text(
        'class A { void f() { Toast.makeText(ctx, "Plain visible message", 0); trKey("Wrapped visible message here"); } }\n',
        encoding="utf-8")
    (src / "app.js").write_text('alert(myT("Wrapped message in javascript"));\nalert("Plain message in javascript");\n', encoding="utf-8")
    plain = {" ".join(h.text.split()) for h in build_scanner("source", tmp_path, ["src"]).scan().hardcoded}
    wrapped = {" ".join(h.text.split()) for h in build_scanner(
        "source", tmp_path, ["src"], t_functions=["trKey", "myT"]).scan().hardcoded}
    assert "Wrapped visible message here" in plain and "Wrapped visible message here" not in wrapped
    assert "Wrapped message in javascript" in plain and "Wrapped message in javascript" not in wrapped
    assert "Plain visible message" in wrapped and "Plain message in javascript" in wrapped


def test_chat_bot_ruby_description_and_go_error_sinks(tmp_path: Path) -> None:
    hits = _scan(tmp_path, "bot.py", (
        "class Cog:\n"
        "    @commands.command()\n"
        "    async def ping(self, ctx):\n"
        '        """Check the bot latency and report it."""\n'
        '        await ctx.send("Pong! The bot is alive")\n'
        '        embed = discord.Embed(title="Friendly Reminder", description="Please read the rules first")\n'
        '        embed.add_field(name="Reason", value="No reason was given")\n'
        '        sock.send("PING command to server")\n'
        '        self.show_toast_msg("File has been deleted!")\n'
    ))
    texts = _texts(hits)
    assert {"Check the bot latency and report it.", "Pong! The bot is alive", "Friendly Reminder",
            "Please read the rules first", "Reason", "No reason was given", "File has been deleted!"} <= texts
    assert "PING command to server" not in _texts([h for h in hits if h.confidence != "low"])
    hits = _scan(tmp_path, "agent.rb", (
        "class A < Agent\n"
        "  description <<~MD\n"
        "    Use this agent to send notifications to people.\n"
        "  MD\n"
        '  def validate\n    errors.add(:base, "You need to provide a valid URL")\n  end\n'
        "end\n"
    ))
    texts = _texts(hits)
    assert any("send notifications to people" in t for t in texts) and "You need to provide a valid URL" in texts
    hits = _scan(tmp_path, "main.go", (
        'func run() error {\n    return fmt.Errorf("expected a geometry column named %q", name)\n}\n'
    ))
    assert not any("expected a geometry column" in t for t in _texts([h for h in hits if h.confidence != "low"]))  # server code logs these: not a sink
