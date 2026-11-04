export const money = (value: number) =>
  value.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
export const eur = (value: number) => `EUR ${money(value)}`;
