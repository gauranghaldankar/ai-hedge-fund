/** Returns ₹ for Indian exchange tickers (.NS, .BO, .BSE), $ otherwise. */
export function getCurrencySymbol(ticker: string): string {
  const upper = ticker.toUpperCase();
  if (upper.endsWith('.NS') || upper.endsWith('.BO') || upper.endsWith('.BSE')) {
    return '₹';
  }
  return '$';
}
