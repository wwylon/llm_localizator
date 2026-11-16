export function Button({ className, ...props }: React.ComponentProps<typeof Primitive>) {
  const [open, setOpen] = useState<string>("");
  return <span>{used} GiB / {total} MiB</span>;
}
const NEWS_SUMMARY_PROMPT = `You are a financial news editor. Summarize these headlines for the user.`;
const DICT = { "Files stay on your computer": "Pliki zostają na Twoim komputerze" };
const unit = "GiB";
const label = locale === "pl" ? "Kaucje" : "Deposits held";
