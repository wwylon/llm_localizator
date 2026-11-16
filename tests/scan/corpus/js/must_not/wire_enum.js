/* must-not: wire / status enums */
var status = "human";
if (row.status === "machine") {
  row.status = "stale";
}
fetch(url, { method: "GET" });
