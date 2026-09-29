
from pathlib import Path
import json
import logging

import pandas as pd


# --------------------------------------------------
# 1. PROJECT CONFIGURATION
# --------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
QUALITY_DIR = PROJECT_ROOT / "docs" / "data_quality"

PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
QUALITY_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)


# --------------------------------------------------
# 2. EXTRACT
# --------------------------------------------------

def extract_data() -> pd.DataFrame:
    """Read the Excel dataset from the raw data folder."""

    excel_files = [
        file
        for file in RAW_DIR.glob("*.xlsx")
        if not file.name.startswith("~$")
    ]

    if not excel_files:
        raise FileNotFoundError(
            f"No .xlsx file found in: {RAW_DIR}\n"
            "Place your retail Excel dataset in data/raw."
        )

    if len(excel_files) > 1:
        raise ValueError(
            "Multiple Excel files found in data/raw. "
            "Keep only the dataset you want to process."
        )

    file_path = excel_files[0]
    logging.info("Reading file: %s", file_path.name)

    df = pd.read_excel(file_path)

    logging.info("Rows extracted: %s", len(df))
    logging.info("Columns found: %s", list(df.columns))

    return df


# --------------------------------------------------
# 3. TRANSFORM
# --------------------------------------------------

def transform_data(df: pd.DataFrame):
    """Clean the data and create analytics columns."""

    original_rows = len(df)

    # Standardize column names
    df.columns = (
        df.columns
        .str.strip()
        .str.replace(r"([a-z])([A-Z])", r"\1_\2", regex=True)
        .str.replace(r"[\s\-]+", "_", regex=True)
        .str.lower()
    )

    # Support common variations in column names
    df = df.rename(
        columns={
            "invoiceno": "invoice_no",
            "stockcode": "stock_code",
            "invoicedate": "invoice_date",
            "unitprice": "unit_price",
            "customerid": "customer_id",
        }
    )

    required_columns = [
        "invoice_no",
        "stock_code",
        "description",
        "quantity",
        "invoice_date",
        "unit_price",
        "customer_id",
        "country",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            f"Dataset is missing expected columns: {missing_columns}"
        )

    # Record quality metrics before cleaning
    missing_before = (
        df.isna().sum().astype(int).to_dict()
    )

    duplicate_rows = int(df.duplicated().sum())

    # Remove exact duplicate records
    df = df.drop_duplicates().copy()

    # Standardize text fields
    for column in [
        "invoice_no",
        "stock_code",
        "description",
        "country",
    ]:
        df[column] = df[column].astype("string").str.strip()

    # Convert data types
    df["invoice_date"] = pd.to_datetime(
        df["invoice_date"],
        errors="coerce",
    )

    df["quantity"] = pd.to_numeric(
        df["quantity"],
        errors="coerce",
    )

    df["unit_price"] = pd.to_numeric(
        df["unit_price"],
        errors="coerce",
    )

    df["customer_id"] = pd.to_numeric(
        df["customer_id"],
        errors="coerce",
    ).astype("Int64")

    # Remove rows missing essential transaction fields
    essential_columns = [
        "invoice_no",
        "stock_code",
        "invoice_date",
        "quantity",
        "unit_price",
    ]

    rows_before_required_check = len(df)

    df = df.dropna(
        subset=essential_columns
    ).copy()

    removed_missing_essential = (
        rows_before_required_check - len(df)
    )

    # Remove rows with blank invoice or stock codes
    valid_codes = (
        df["invoice_no"].notna()
        & df["stock_code"].notna()
        & df["invoice_no"].ne("")
        & df["stock_code"].ne("")
    )

    removed_blank_codes = int((~valid_codes).sum())
    df = df.loc[valid_codes].copy()

    # Flag cancellations and returns instead of deleting them
    df["transaction_type"] = "SALE"

    cancellation_mask = (
        df["invoice_no"]
        .str.upper()
        .str.startswith("C", na=False)
    )

    return_mask = (
        ~cancellation_mask
        & df["quantity"].lt(0)
    )

    df.loc[cancellation_mask, "transaction_type"] = (
        "CANCELLATION"
    )

    df.loc[return_mask, "transaction_type"] = "RETURN"

    # Calculate line value
    df["line_total"] = (
        df["quantity"] * df["unit_price"]
    ).round(2)

    # Add calendar attributes for analysis
    df["invoice_year"] = df["invoice_date"].dt.year
    df["invoice_month"] = df["invoice_date"].dt.month
    df["invoice_day"] = df["invoice_date"].dt.day
    df["invoice_year_month"] = (
        df["invoice_date"].dt.to_period("M").astype("string")
    )

    # Sort for easier inspection
    df = df.sort_values(
        ["invoice_date", "invoice_no", "stock_code"]
    ).reset_index(drop=True)

    # Quality report
    quality_report = {
        "source_rows": int(original_rows),
        "rows_after_exact_deduplication": int(
            original_rows - duplicate_rows
        ),
        "exact_duplicate_rows_removed": duplicate_rows,
        "rows_removed_missing_essential_fields": int(
            removed_missing_essential
        ),
        "rows_removed_blank_codes": removed_blank_codes,
        "final_rows": int(len(df)),
        "missing_values_before_cleaning": missing_before,
        "missing_values_after_cleaning": (
            df.isna().sum().astype(int).to_dict()
        ),
        "sale_rows": int(
            df["transaction_type"].eq("SALE").sum()
        ),
        "return_rows": int(
            df["transaction_type"].eq("RETURN").sum()
        ),
        "cancellation_rows": int(
            df["transaction_type"].eq("CANCELLATION").sum()
        ),
        "unique_invoices": int(df["invoice_no"].nunique()),
        "unique_products": int(df["stock_code"].nunique()),
        "unique_customers": int(df["customer_id"].nunique()),
        "date_min": str(df["invoice_date"].min()),
        "date_max": str(df["invoice_date"].max()),
    }

    return df, quality_report


# --------------------------------------------------
# 4. LOAD
# --------------------------------------------------

def load_data(
    df: pd.DataFrame,
    quality_report: dict,
) -> None:
    """Save the cleaned dataset and quality report."""

    output_csv = (
        PROCESSED_DIR / "cleaned_transactions.csv"
    )

    output_report = (
        QUALITY_DIR / "etl_quality_report.json"
    )

    df.to_csv(
        output_csv,
        index=False,
        encoding="utf-8-sig",
    )

    with open(output_report, "w", encoding="utf-8") as file:
        json.dump(
            quality_report,
            file,
            indent=4,
            ensure_ascii=False,
        )

    logging.info("Cleaned data saved: %s", output_csv)
    logging.info("Quality report saved: %s", output_report)


# --------------------------------------------------
# 5. RUN PIPELINE
# --------------------------------------------------

def main():
    logging.info("Retail360 ETL pipeline started")

    raw_df = extract_data()

    cleaned_df, quality_report = transform_data(raw_df)

    load_data(cleaned_df, quality_report)

    logging.info("ETL pipeline completed successfully")
    logging.info(
        "Final rows: %s",
        quality_report["final_rows"],
    )
    logging.info(
        "Unique customers: %s",
        quality_report["unique_customers"],
    )


if __name__ == "__main__":
    main()
