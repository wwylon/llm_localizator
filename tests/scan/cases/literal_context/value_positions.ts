export function actionLabel(a: string, armed: boolean): string {
  if (a === "NextHand") return "Next hand";
  const label = armed ? "Confirm fold" : "Fold";
  return label || "Waiting for opponent";
}
export const MODES = [{ value: "hvb", label: "Human vs bot" }];
