import argparse

import pandas as pd

TARGET_COLUMNS = ["Date", "Description", "Category", "Amount", "Type / Extended Notes"]


def _strip_strings(df: pd.DataFrame) -> pd.DataFrame:
    """Strip whitespace from column names and string values."""
    df.columns = df.columns.str.strip()
    for col in df.select_dtypes(include=["object"]).columns:
        df[col] = df[col].apply(lambda v: v.strip() if isinstance(v, str) else v)
    return df


def _clean_amount(series: pd.Series) -> pd.Series:
    """Remove currency symbols/commas and coerce to float."""
    cleaned = series.astype(str).str.replace(r"[\$,]", "", regex=True).str.strip()
    return pd.to_numeric(cleaned, errors="coerce")


def _combine_notes(df: pd.DataFrame, cols: list[str], sep: str = " | ") -> pd.Series:
    """Combine secondary fields into one string, omitting NaN / empty values."""
    def _row(row):
        parts = []
        for c in cols:
            if c not in row:
                continue
            val = row[c]
            if pd.isna(val):
                continue
            s = str(val).strip()
            if s and s.lower() != "nan":
                parts.append(s)
        return sep.join(parts)

    return df.apply(_row, axis=1)


def _normalize_amex(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = _strip_strings(df)

    out = pd.DataFrame()
    out["Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.strftime("%Y-%m-%d")
    out["Description"] = df["Description"] if "Description" in df.columns else ""
    out["Category"] = df["Category"] if "Category" in df.columns else ""
    out["Amount"] = _clean_amount(df["Amount"]) if "Amount" in df.columns else pd.NA
    out["Type / Extended Notes"] = _combine_notes(
        df, ["Appears On Your Statement As", "Extended Details"]
    )
    return out[TARGET_COLUMNS]


def _normalize_chase(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = _strip_strings(df)

    out = pd.DataFrame()
    out["Date"] = pd.to_datetime(df["Transaction Date"], errors="coerce").dt.strftime("%Y-%m-%d")
    out["Description"] = df["Description"] if "Description" in df.columns else ""
    out["Category"] = df["Category"] if "Category" in df.columns else ""
    out["Amount"] = _clean_amount(df["Amount"]) if "Amount" in df.columns else pd.NA
    out["Type / Extended Notes"] = _combine_notes(df, ["Type", "Memo"])
    return out[TARGET_COLUMNS]


def main() -> None:
    parser = argparse.ArgumentParser(description="Consolidate AMEX and Chase CSVs.")
    parser.add_argument("amex_file", help="Path to AMEX CSV file")
    parser.add_argument("chase_file", help="Path to Chase CSV file")
    parser.add_argument(
        "-o", "--output",
        dest="output_file",
        default="consolidated_transactions.csv",
        help="Output CSV path (default: consolidated_transactions.csv)",
    )
    args = parser.parse_args()

    amex = _normalize_amex(args.amex_file)
    chase = _normalize_chase(args.chase_file)

    amex_count = len(amex)
    chase_count = len(chase)

    combined = pd.concat([amex, chase], ignore_index=True)
    combined["Date"] = pd.to_datetime(combined["Date"], errors="coerce")
    combined = combined.sort_values(by="Date", ascending=False)
    combined["Date"] = combined["Date"].dt.strftime("%Y-%m-%d")
    combined = combined.drop_duplicates()
    combined = combined[TARGET_COLUMNS]

    combined.to_csv(args.output_file, index=False)

    print(f"AMEX rows:        {amex_count}")
    print(f"Chase rows:       {chase_count}")
    print(f"Consolidated rows: {len(combined)} (duplicates removed: {amex_count + chase_count - len(combined)})")
    print(f"Output written to: {args.output_file}")


if __name__ == "__main__":
    main()
