
from pathlib import Path
from getpass import getpass
import logging

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL


# ============================================================
# Retail360 | Load cleaned data into PostgreSQL
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CSV_FILE = PROJECT_ROOT / "data" / "processed" / "cleaned_transactions.csv"

DB_HOST = "localhost"
DB_PORT = 5432
DB_NAME = "retail360"
DB_USER = "postgres"

BATCH_SIZE = 5000

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)


def get_database_engine():
    """Connect to the local Retail360 PostgreSQL database."""

    password = getpass("Enter PostgreSQL password for postgres: ")

    connection_url = URL.create(
        drivername="postgresql+psycopg",
        username=DB_USER,
        password=password,
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
    )

    return create_engine(
        connection_url,
        pool_pre_ping=True,
    )


def load_source_data():
    """Read and prepare the cleaned CSV."""

    if not CSV_FILE.exists():
        raise FileNotFoundError(
            f"Cleaned CSV not found: {CSV_FILE}\n"
            "Run the cleaning ETL pipeline first."
        )

    logging.info("Reading cleaned transactions...")
    df = pd.read_csv(
        CSV_FILE,
        dtype={
            "invoice_no": "string",
            "stock_code": "string",
            "description": "string",
            "country": "string",
        },
        low_memory=False,
    )

    required = [
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

    missing = [column for column in required if column not in df.columns]

    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    df["invoice_no"] = df["invoice_no"].str.strip()
    df["stock_code"] = df["stock_code"].str.strip()
    df["description"] = df["description"].str.strip()
    df["country"] = df["country"].str.strip()

    df["invoice_date"] = pd.to_datetime(
        df["invoice_date"], errors="coerce"
    )
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")
    df["unit_price"] = pd.to_numeric(df["unit_price"], errors="coerce")
    df["line_total"] = pd.to_numeric(df["line_total"], errors="coerce")
    df["customer_id"] = pd.to_numeric(
        df["customer_id"], errors="coerce"
    ).astype("Int64")

    df = df.dropna(
        subset=[
            "invoice_no",
            "stock_code",
            "invoice_date",
            "quantity",
            "unit_price",
            "line_total",
        ]
    ).copy()

    df = df[
        df["invoice_no"].ne("")
        & df["stock_code"].ne("")
    ].copy()

    df["country"] = df["country"].fillna("Unknown").replace("", "Unknown")
    df["description"] = df["description"].fillna("Unknown").replace(
        "", "Unknown"
    )

    df["transaction_type"] = df["transaction_type"].astype(str).str.upper()

    allowed_types = {"SALE", "RETURN", "CANCELLATION"}
    invalid_types = set(df["transaction_type"].unique()) - allowed_types

    if invalid_types:
        raise ValueError(
            f"Unexpected transaction types: {sorted(invalid_types)}"
        )

    # The source dataset uses whole-number quantities.
    if not (df["quantity"] % 1 == 0).all():
        raise ValueError("Found non-integer quantities.")

    df["quantity"] = df["quantity"].astype("int64")
    df["invoice_date_only"] = df["invoice_date"].dt.date
    df["date_key"] = df["invoice_date"].dt.strftime("%Y%m%d").astype(int)

    logging.info("Prepared %s transaction rows.", len(df))
    return df


def records_for_sql(df):
    """Convert pandas missing values to Python None for SQL."""

    records = df.to_dict(orient="records")

    for record in records:
        for key, value in record.items():
            if pd.isna(value):
                record[key] = None
            elif hasattr(value, "item"):
                record[key] = value.item()

    return records


def execute_batches(connection, sql, records):
    """Execute parameterized SQL in manageable batches."""

    for start in range(0, len(records), BATCH_SIZE):
        batch = records[start:start + BATCH_SIZE]
        connection.execute(text(sql), batch)


def load_dimensions(connection, df):
    """Insert or update date, customer, product and country dimensions."""

    # --------------------------------------------------------
    # DATE DIMENSION
    # --------------------------------------------------------
    dates = (
        df[["date_key", "invoice_date_only"]]
        .drop_duplicates()
        .sort_values("date_key")
    )

    date_records = []

    for row in dates.itertuples(index=False):
        date_value = row.invoice_date_only

        date_records.append({
            "date_key": int(row.date_key),
            "full_date": date_value,
            "day_number": date_value.day,
            "month_number": date_value.month,
            "month_name": date_value.strftime("%B"),
            "quarter_number": (date_value.month - 1) // 3 + 1,
            "year_number": date_value.year,
            "year_month": date_value.strftime("%Y-%m"),
            "day_of_week": date_value.strftime("%A"),
            "is_weekend": date_value.weekday() >= 5,
        })

    execute_batches(
        connection,
        """
        INSERT INTO retail360.dim_date (
            date_key, full_date, day_number, month_number,
            month_name, quarter_number, year_number,
            year_month, day_of_week, is_weekend
        )
        VALUES (
            :date_key, :full_date, :day_number, :month_number,
            :month_name, :quarter_number, :year_number,
            :year_month, :day_of_week, :is_weekend
        )
        ON CONFLICT (date_key) DO NOTHING
        """,
        date_records,
    )

    # --------------------------------------------------------
    # CUSTOMER DIMENSION
    # --------------------------------------------------------
    customer_rows = df[df["customer_id"].notna()].copy()

    if not customer_rows.empty:
        customer_summary = (
            customer_rows.groupby("customer_id")["invoice_date_only"]
            .agg(["min", "max"])
            .reset_index()
        )

        customer_records = [
            {
                "source_customer_id": int(row.customer_id),
                "first_purchase_date": row["min"],
                "last_purchase_date": row["max"],
            }
            for _, row in customer_summary.iterrows()
        ]

        execute_batches(
            connection,
            """
            INSERT INTO retail360.dim_customer (
                source_customer_id,
                first_purchase_date,
                last_purchase_date
            )
            VALUES (
                :source_customer_id,
                :first_purchase_date,
                :last_purchase_date
            )
            ON CONFLICT (source_customer_id)
            DO UPDATE SET
                first_purchase_date = EXCLUDED.first_purchase_date,
                last_purchase_date = EXCLUDED.last_purchase_date
            """,
            customer_records,
        )

    # --------------------------------------------------------
    # PRODUCT DIMENSION
    # --------------------------------------------------------
    products = (
        df[["stock_code", "description"]]
        .drop_duplicates()
        .copy()
    )

    # Pick one description per stock code.
    products = products.drop_duplicates(
        subset=["stock_code"], keep="last"
    )

    product_records = [
        {
            "source_stock_code": str(row.stock_code),
            "product_name": (
                None if pd.isna(row.description)
                else str(row.description)
            ),
        }
        for row in products.itertuples(index=False)
    ]

    execute_batches(
        connection,
        """
        INSERT INTO retail360.dim_product (
            source_stock_code, product_name
        )
        VALUES (
            :source_stock_code, :product_name
        )
        ON CONFLICT (source_stock_code)
        DO UPDATE SET product_name = EXCLUDED.product_name
        """,
        product_records,
    )

    # --------------------------------------------------------
    # COUNTRY DIMENSION
    # --------------------------------------------------------
    countries = sorted(df["country"].dropna().unique().tolist())

    country_records = [
        {"country_name": str(country)}
        for country in countries
    ]

    execute_batches(
        connection,
        """
        INSERT INTO retail360.dim_country (country_name)
        VALUES (:country_name)
        ON CONFLICT (country_name) DO NOTHING
        """,
        country_records,
    )

    logging.info("Dimension tables loaded.")


def load_fact_table(connection, df):
    """Refresh fact_sales from the cleaned source dataset."""

    # Full refresh makes repeated runs predictable and avoids
    # inserting the same source transactions twice.
    connection.execute(
        text("TRUNCATE TABLE retail360.fact_sales RESTART IDENTITY")
    )

    customer_map = dict(
        connection.execute(
            text("""
                SELECT source_customer_id, customer_key
                FROM retail360.dim_customer
                WHERE source_customer_id IS NOT NULL
            """)
        ).all()
    )

    product_map = dict(
        connection.execute(
            text("""
                SELECT source_stock_code, product_key
                FROM retail360.dim_product
            """)
        ).all()
    )

    country_map = dict(
        connection.execute(
            text("""
                SELECT country_name, country_key
                FROM retail360.dim_country
            """)
        ).all()
    )

    fact_df = df.copy()

    fact_df["customer_key"] = (
        fact_df["customer_id"]
        .map(lambda value: customer_map.get(int(value), 0)
             if pd.notna(value) else 0)
    )

    fact_df["product_key"] = fact_df["stock_code"].map(product_map)
    fact_df["country_key"] = fact_df["country"].map(country_map)

    if fact_df[["product_key", "country_key"]].isna().any().any():
        raise ValueError(
            "A product or country key could not be matched to its dimension."
        )

    fact_columns = [
        "date_key",
        "customer_key",
        "product_key",
        "country_key",
        "invoice_no",
        "transaction_type",
        "quantity",
        "unit_price",
        "line_total",
    ]

    fact_df = fact_df[fact_columns].copy()

    fact_records = records_for_sql(fact_df)

    insert_sql = """
        INSERT INTO retail360.fact_sales (
            date_key,
            customer_key,
            product_key,
            country_key,
            invoice_no,
            transaction_type,
            quantity,
            unit_price,
            line_total
        )
        VALUES (
            :date_key,
            :customer_key,
            :product_key,
            :country_key,
            :invoice_no,
            :transaction_type,
            :quantity,
            :unit_price,
            :line_total
        )
    """

    execute_batches(connection, insert_sql, fact_records)

    logging.info("Loaded %s rows into fact_sales.", len(fact_records))


def main():
    logging.info("Retail360 warehouse load started.")

    df = load_source_data()
    engine = get_database_engine()

    try:
        # All dimension and fact changes commit together.
        with engine.begin() as connection:
            load_dimensions(connection, df)
            load_fact_table(connection, df)

            counts = connection.execute(
                text("""
                    SELECT
                        (SELECT COUNT(*) FROM retail360.dim_date)
                            AS dates,
                        (SELECT COUNT(*) FROM retail360.dim_customer)
                            AS customers,
                        (SELECT COUNT(*) FROM retail360.dim_product)
                            AS products,
                        (SELECT COUNT(*) FROM retail360.dim_country)
                            AS countries,
                        (SELECT COUNT(*) FROM retail360.fact_sales)
                            AS fact_rows
                """)
            ).mappings().one()

        print("\n" + "=" * 50)
        print("RETAIL360 WAREHOUSE LOAD COMPLETE")
        print("=" * 50)
        for name, count in counts.items():
            print(f"{name.replace('_', ' ').title():20}: {count:,}")
        print("=" * 50)

    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
