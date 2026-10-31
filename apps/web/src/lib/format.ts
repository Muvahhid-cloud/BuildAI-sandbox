/**
 * Currency-agnostic money formatting. Amounts travel as decimal strings (never floats);
 * Intl.NumberFormat formats the string exactly without converting to a JS number.
 */
export function formatMoney(
  amount: string,
  currency: string,
  opts: { locale?: string; minorUnits?: number } = {},
): string {
  const fmt = new Intl.NumberFormat(opts.locale ?? "en-US", {
    style: "currency",
    currency,
    currencyDisplay: "narrowSymbol",
    minimumFractionDigits: opts.minorUnits,
    maximumFractionDigits: opts.minorUnits,
  });
  return fmt.format(amount as Intl.StringNumericLiteral);
}
