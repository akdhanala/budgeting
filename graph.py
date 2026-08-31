import re
from typing import TypedDict
import argparse

import pandas as pd
from langgraph.graph import START, END, StateGraph

_WS_RE = re.compile(r"\s+")


TARGET_COLUMNS = ["Date", "Description", "Category", "Amount", "Type / Extended Notes"]


class BudgetState(TypedDict, total=False):
    amex_path: str
    chase_path: str
    consolidated_df: pd.DataFrame
    consolidated_rows: int


def _strip_strings(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = df.columns.str.strip().str.replace(r"\s+", " ", regex=True)
    for col in df.select_dtypes(include=["object", "string"]).columns:
        df[col] = df[col].apply(
            lambda v: _WS_RE.sub(" ", v.strip()) if isinstance(v, str) else v
        )
    if "Description" in df.columns:
        df["Description"] = df["Description"].apply(
            lambda v: v.lower() if isinstance(v, str) else v
        )
    return df


def _clean_amount(series: pd.Series) -> pd.Series:
    cleaned = series.astype(str).str.replace(r"[\$,]", "", regex=True).str.strip()
    return pd.to_numeric(cleaned, errors="coerce")


def _combine_notes(df: pd.DataFrame, cols: list[str], sep: str = " | ") -> pd.Series:
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


def _normalize_amex_df(df: pd.DataFrame) -> pd.DataFrame:
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


def _normalize_chase_df(df: pd.DataFrame) -> pd.DataFrame:
    df = _strip_strings(df)
    out = pd.DataFrame()
    out["Date"] = pd.to_datetime(df["Transaction Date"], errors="coerce").dt.strftime("%Y-%m-%d")
    out["Description"] = df["Description"] if "Description" in df.columns else ""
    out["Category"] = df["Category"] if "Category" in df.columns else ""
    out["Amount"] = _clean_amount(df["Amount"]) if "Amount" in df.columns else pd.NA
    out["Type / Extended Notes"] = _combine_notes(df, ["Type", "Memo"])
    return out[TARGET_COLUMNS]


def _combine_frames(amex: pd.DataFrame, chase: pd.DataFrame) -> pd.DataFrame:
    combined = pd.concat([amex, chase], ignore_index=True)
    combined["Date"] = pd.to_datetime(combined["Date"], errors="coerce")
    combined = combined.sort_values(by="Date", ascending=False)
    combined["Date"] = combined["Date"].dt.strftime("%Y-%m-%d")
    return combined[TARGET_COLUMNS]


def consolidate_node(state: BudgetState) -> dict:
    amex_raw = pd.read_csv(state["amex_path"])
    chase_raw = pd.read_csv(state["chase_path"])
    amex = _normalize_amex_df(amex_raw)
    chase = _normalize_chase_df(chase_raw)
    combined = _combine_frames(amex, chase)
    return {
        "consolidated_df": combined,
        "consolidated_rows": len(combined),
    }


graph = StateGraph(BudgetState)
graph.add_node("consolidate", consolidate_node)
graph.add_edge(START, "consolidate")
graph.add_edge("consolidate", END)
graph = graph.compile()


def main():
    parser = argparse.ArgumentParser(description="Run consolidate graph")
    parser.add_argument("amex_file", nargs="?", help="Path to AMEX CSV file")
    parser.add_argument("chase_file", nargs="?", help="Path to Chase CSV file")
    args = parser.parse_args()

    amex_path = args.amex_file or input("AMEX CSV path: ").strip()
    chase_path = args.chase_file or input("Chase CSV path: ").strip()

    if not amex_path or not chase_path:
        parser.error("Both AMEX and Chase CSV paths are required.")

    print(graph.get_graph().draw_ascii())
    result = graph.invoke({"amex_path": amex_path, "chase_path": chase_path})
    print(f"Consolidated rows: {result['consolidated_rows']}")


if __name__ == "__main__":
    main()
