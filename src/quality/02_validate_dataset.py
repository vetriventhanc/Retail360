
from pathlib import Path
import json
import logging

import pandas as pd


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "cleaned_transactions.csv"
)

REPORT_DIR = PROJECT_ROOT / "docs" / "data_quality"
REPORT_FILE = REPORT_DIR / "validation_report.json"

REPORT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s | %(message)s",
)


# --------------------------------------------------
# VALIDATION RULES
# --------------------------------------------------

REQUIRED_COLUMNS = [
    "invoice_no",
    "stock_code",
    "description",
    "quantity",
    "invoice_date",
    "unit_price",
    "customer_id",
    "country",
    "transaction_type",
    "line_total",
]


def validate_dataset(df: pd.DataFrame) -> dict:
    checks = {}

    # 1. Dataset is not empty
    checks["dataset_not_empty"] = {
        "passed": not df.empty,
        "details": f"Rows found: {len(df)}",
    }

    # 2. Required columns exist
    missing_columns = [
        column
        for column in REQUIRED_COLUMNS
        if column not in df.columns
    ]

    checks["required_columns_present"] = {
        "passed": len(missing_columns) == 0,
        "details": (
            "All required columns exist."
            if not missing_columns
            else f"Missing columns: {missing_columns}"
        ),
    }

    # Stop checks that depend on required columns if schema is invalid
    if missing_columns:
        return {
            "overall_passed": False,
            "row_count": int(len(df)),
            "checks": checks,
        }

    # 3. No exact duplicate rows
    duplicate_count = int(df.duplicated().sum())

    checks["no_duplicate_rows"] = {
        "passed": duplicate_count == 0,
        "details": f"Duplicate rows: {duplicate_count}",
    }

    # 4. Essential fields are populated
    essential_columns = [
        "invoice_no",
        "stock_code",
        "invoice_date",
        "quantity",
        "unit_price",
    ]

    missing_essential = int(
        df[essential_columns].isna().any(axis=1).sum()
    )

    checks["essential_fields_populated"] = {
        "passed": missing_essential == 0,
        "details": (
            f"Rows missing essential fields: {missing_essential}"
        ),
    }

    # 5. Numeric values are valid
    numeric_columns = ["quantity", "unit_price", "line_total"]

    numeric_invalid = {}

    for column in numeric_columns:
        converted = pd.to_numeric(df[column], errors="coerce")
        invalid_count = int(converted.isna().sum())

        numeric_invalid[column] = invalid_count

    checks["numeric_fields_valid"] = {
        "passed": all(
            count == 0 for count in numeric_invalid.values()
        ),
        "details": numeric_invalid,
    }

    # 6. Dates are valid
    parsed_dates = pd.to_datetime(
        df["invoice_date"],
        errors="coerce",
    )

    invalid_dates = int(parsed_dates.isna().sum())

    checks["invoice_dates_valid"] = {
        "passed": invalid_dates == 0,
        "details": f"Invalid dates: {invalid_dates}",
    }

    # 7. Line totals match quantity * unit price
    expected_total = (
        pd.to_numeric(df["quantity"], errors="coerce")
        * pd.to_numeric(df["unit_price"], errors="coerce")
    )

    actual_total = pd.to_numeric(
        df["line_total"],
        errors="coerce",
    )

    total_mismatch = (
        expected_total.sub(actual_total).abs() > 0.011
    )

    mismatch_count = int(total_mismatch.fillna(True).sum())

    checks["line_totals_correct"] = {
        "passed": mismatch_count == 0,
        "details": f"Line total mismatches: {mismatch_count}",
    }

    # 8. Transaction classifications are valid
    allowed_types = {"SALE", "RETURN", "CANCELLATION"}

    unexpected_types = sorted(
        set(df["transaction_type"].dropna().unique())
        - allowed_types
    )

    missing_types = int(df["transaction_type"].isna().sum())

    checks["transaction_types_valid"] = {
        "passed": (
            not unexpected_types and missing_types == 0
        ),
        "details": {
            "unexpected_types": unexpected_types,
            "missing_types": missing_types,
        },
    }

    # 9. Summary metrics
    summary = {
        "row_count": int(len(df)),
        "unique_invoices": int(df["invoice_no"].nunique()),
        "unique_products": int(df["stock_code"].nunique()),
        "unique_customers": int(df["customer_id"].nunique()),
        "transaction_type_counts": {
            str(key): int(value)
            for key, value in (
                df["transaction_type"].value_counts(dropna=False)
                .items()
            )
        },
    }

    overall_passed = all(
        check["passed"] for check in checks.values()
    )

    return {
        "overall_passed": overall_passed,
        "summary": summary,
        "checks": checks,
    }


# --------------------------------------------------
# RUN VALIDATION
# --------------------------------------------------

def main():
    if not DATA_FILE.exists():
        raise FileNotFoundError(
            f"Cleaned dataset not found: {DATA_FILE}\n"
            "Run the ETL pipeline first."
        )

    logging.info("Loading cleaned dataset...")
    df = pd.read_csv(DATA_FILE)

    logging.info("Running data quality checks...")
    report = validate_dataset(df)

    with open(REPORT_FILE, "w", encoding="utf-8") as file:
        json.dump(report, file, indent=4, ensure_ascii=False)

    logging.info("Report saved to: %s", REPORT_FILE)

    print("\n" + "=" * 50)
    print("RETAIL360 DATA QUALITY REPORT")
    print("=" * 50)

    for name, result in report["checks"].items():
        status = "PASS" if result["passed"] else "FAIL"
        print(f"[{status}] {name}: {result['details']}")

    print("-" * 50)

    if report["overall_passed"]:
        print("RESULT: ALL CHECKS PASSED")
    else:
        print("RESULT: SOME CHECKS FAILED")
        print("Review the report before proceeding.")

    print("=" * 50)


if __name__ == "__main__":
    main()
