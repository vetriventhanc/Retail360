import pandas as pd
import plotly.express as px
import streamlit as st

from sqlalchemy import URL, bindparam, create_engine, text


# ============================================================
# Retail360 | Product Analysis
# ============================================================

st.set_page_config(
    page_title="Retail360 | Product Analysis",
    page_icon="📦",
    layout="wide",
)


# -----------------------------
# Styling
# -----------------------------

st.markdown(
    """
    <style>
        .block-container {
            padding-top: 1.5rem;
            padding-bottom: 2rem;
        }

        div[data-testid="stMetric"] {
            background: #151c2c;
            border: 1px solid #29344a;
            padding: 16px 18px;
            border-radius: 12px;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


# -----------------------------
# Check database connection
# -----------------------------

if "db_config" not in st.session_state:
    st.title("📦 Product Analysis")
    st.warning(
        "First open the Retail360 Analytics home page, "
        "enter your PostgreSQL password, and connect "
        "to the warehouse."
    )
    st.stop()


config = st.session_state["db_config"]


@st.cache_resource
def get_engine(host, port, database, username, password):
    url = URL.create(
        drivername="postgresql+psycopg",
        username=username,
        password=password,
        host=host,
        port=int(port),
        database=database,
    )

    return create_engine(
        url,
        pool_pre_ping=True,
    )


engine = get_engine(
    config["host"],
    config["port"],
    config["database"],
    config["username"],
    config["password"],
)


def read_sql(query, params=None, expanding=()):
    statement = text(query)

    if expanding:
        statement = statement.bindparams(
            *[
                bindparam(name, expanding=True)
                for name in expanding
            ]
        )

    with engine.connect() as connection:
        return pd.read_sql(
            statement,
            connection,
            params=params or {},
        )


# -----------------------------
# Header
# -----------------------------

st.title("📦 Product Analysis")

st.markdown(
    "Explore product sales, cancellations, "
    "and recorded return quantities."
)


# -----------------------------
# Load filter values
# -----------------------------

try:
    date_bounds = read_sql(
        """
        SELECT
            MIN(full_date) AS min_date,
            MAX(full_date) AS max_date
        FROM retail360.dim_date
        """
    )

    country_df = read_sql(
        """
        SELECT DISTINCT country_name
        FROM retail360.dim_country
        WHERE country_name IS NOT NULL
        ORDER BY country_name
        """
    )

    if (
        date_bounds.empty
        or pd.isna(date_bounds.loc[0, "min_date"])
    ):
        st.warning(
            "No dates are available in the date dimension."
        )
        st.stop()

    min_date = pd.to_datetime(
        date_bounds.loc[0, "min_date"]
    ).date()

    max_date = pd.to_datetime(
        date_bounds.loc[0, "max_date"]
    ).date()

    country_options = country_df[
        "country_name"
    ].tolist()

except Exception as exc:
    st.error("Could not load the warehouse filters.")
    st.code(str(exc))
    st.stop()


# -----------------------------
# Sidebar filters
# -----------------------------

with st.sidebar:
    st.header("Product filters")

    selected_dates = st.date_input(
        "Transaction date range",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
        key="product_date_range",
    )

    selected_countries = st.multiselect(
        "Countries",
        options=country_options,
        default=[],
        key="product_countries",
        help="Leave empty to include all countries.",
    )


if isinstance(selected_dates, (tuple, list)):
    if len(selected_dates) == 2:
        start_date, end_date = selected_dates
    elif len(selected_dates) == 1:
        start_date = end_date = selected_dates[0]
    else:
        start_date, end_date = min_date, max_date
else:
    start_date = end_date = selected_dates


if start_date > end_date:
    st.error("The start date must be before the end date.")
    st.stop()


# -----------------------------
# Build SQL filters
# -----------------------------

country_filter = ""

params = {
    "start_date": start_date,
    "end_date": end_date,
}

expanding = []

if selected_countries:
    country_filter = """
        AND co.country_name IN :countries
    """

    params["countries"] = selected_countries
    expanding.append("countries")


# -----------------------------
# Product-level analysis
# -----------------------------

product_query = f"""
    SELECT
        p.product_key,
        p.source_stock_code,
        p.product_name,

        COALESCE(
            SUM(f.line_total) FILTER (
                WHERE f.transaction_type = 'SALE'
            ),
            0
        ) AS gross_sales,

        COALESCE(
            SUM(f.quantity) FILTER (
                WHERE f.transaction_type = 'SALE'
            ),
            0
        ) AS units_sold,

        COALESCE(
            ABS(
                SUM(f.line_total) FILTER (
                    WHERE f.transaction_type = 'CANCELLATION'
                )
            ),
            0
        ) AS cancellation_value,

        COUNT(*) FILTER (
            WHERE f.transaction_type = 'CANCELLATION'
        ) AS cancellation_lines,

        COALESCE(
            ABS(
                SUM(f.quantity) FILTER (
                    WHERE f.transaction_type = 'RETURN'
                )
            ),
            0
        ) AS returned_units,

        COUNT(*) FILTER (
            WHERE f.transaction_type = 'RETURN'
        ) AS return_lines,

        COUNT(DISTINCT f.invoice_no) FILTER (
            WHERE f.transaction_type = 'SALE'
        ) AS sales_invoices

    FROM retail360.fact_sales f

    JOIN retail360.dim_date d
        ON f.date_key = d.date_key

    JOIN retail360.dim_country co
        ON f.country_key = co.country_key

    JOIN retail360.dim_product p
        ON f.product_key = p.product_key

    WHERE d.full_date >= :start_date
      AND d.full_date <= :end_date
      {country_filter}

    GROUP BY
        p.product_key,
        p.source_stock_code,
        p.product_name

    ORDER BY gross_sales DESC
"""


try:
    statement = text(product_query)

    if expanding:
        statement = statement.bindparams(
            *[
                bindparam(name, expanding=True)
                for name in expanding
            ]
        )

    with engine.connect() as connection:
        products = pd.read_sql(
            statement,
            connection,
            params=params,
        )

except Exception as exc:
    st.error("The product analysis query failed.")
    st.code(str(exc))
    st.info(
        "Check the product and fact table column names "
        "in your PostgreSQL schema."
    )
    st.stop()


if products.empty:
    st.warning(
        "No product transactions match these filters."
    )
    st.stop()


# -----------------------------
# Clean numeric columns
# -----------------------------

numeric_columns = [
    "gross_sales",
    "units_sold",
    "cancellation_value",
    "cancellation_lines",
    "returned_units",
    "return_lines",
    "sales_invoices",
]

for column in numeric_columns:
    products[column] = pd.to_numeric(
        products[column],
        errors="coerce",
    ).fillna(0)


# -----------------------------
# Calculate metrics
# -----------------------------

products["net_sales"] = (
    products["gross_sales"]
    - products["cancellation_value"]
)

total_gross_sales = products["gross_sales"].sum()

total_cancellation_value = (
    products["cancellation_value"].sum()
)

total_net_sales = products["net_sales"].sum()

total_units = products["units_sold"].sum()

total_returned_units = products["returned_units"].sum()

total_return_lines = int(
    products["return_lines"].sum()
)

total_cancellation_lines = int(
    products["cancellation_lines"].sum()
)

total_sales_invoices = int(
    products["sales_invoices"].sum()
)

product_count = products.loc[
    products["gross_sales"] > 0,
    "product_key",
].nunique()

return_line_rate = (
    total_return_lines / total_sales_invoices * 100
    if total_sales_invoices > 0
    else 0
)


# -----------------------------
# Reporting period
# -----------------------------

st.caption(
    f"Period: {start_date:%d %b %Y} "
    f"– {end_date:%d %b %Y}"
)


# -----------------------------
# KPI cards
# -----------------------------

k1, k2, k3, k4 = st.columns(4)

k1.metric(
    "Gross Sales",
    f"{total_gross_sales:,.2f}",
)

k2.metric(
    "Net Sales After Cancellations",
    f"{total_net_sales:,.2f}",
    help=(
        "Gross sales minus recorded cancellation value. "
        "Return monetary values are unavailable in the "
        "source RETURN records."
    ),
)

k3.metric(
    "Units Sold",
    f"{total_units:,.0f}",
)

k4.metric(
    "Products Sold",
    f"{product_count:,}",
)


k5, k6, k7, k8 = st.columns(4)

k5.metric(
    "Cancellation Value",
    f"{total_cancellation_value:,.2f}",
)

k6.metric(
    "Returned Units",
    f"{total_returned_units:,.0f}",
)

k7.metric(
    "Return Lines",
    f"{total_return_lines:,}",
)

k8.metric(
    "Cancellation Lines",
    f"{total_cancellation_lines:,}",
)


st.info(
    "Return records contain zero unit prices and zero "
    "line totals in the current warehouse. Returned "
    "quantities are shown, but return monetary value "
    "cannot be calculated from those records."
)

st.divider()


# -----------------------------
# Top products by gross sales
# -----------------------------

st.subheader("Top 10 products by gross sales")

top_revenue = (
    products[products["gross_sales"] > 0]
    .nlargest(10, "gross_sales")
    .copy()
)


if top_revenue.empty:
    st.info("No positive sales found for this period.")

else:
    top_revenue["product_label"] = (
        top_revenue["source_stock_code"].astype(str)
        + " — "
        + top_revenue["product_name"].fillna("Unknown")
    )

    fig_revenue = px.bar(
        top_revenue.sort_values("gross_sales"),
        x="gross_sales",
        y="product_label",
        orientation="h",
        text="gross_sales",
        labels={
            "gross_sales": "Gross Sales",
            "product_label": "Product",
        },
        template="plotly_dark",
    )

    fig_revenue.update_traces(
        texttemplate="%{x:,.0f}",
        textposition="outside",
        cliponaxis=False,
        hovertemplate=(
            "%{y}<br>"
            "Gross sales: %{x:,.2f}"
            "<extra></extra>"
        ),
    )

    fig_revenue.update_layout(
        height=500,
        margin=dict(l=10, r=70, t=20, b=10),
    )

    st.plotly_chart(
        fig_revenue,
        use_container_width=True,
    )


# -----------------------------
# Units sold vs revenue
# -----------------------------

st.subheader("Product sales comparison")

scatter_data = products[
    (products["gross_sales"] > 0)
    & (products["units_sold"] > 0)
].copy()


if scatter_data.empty:
    st.info(
        "Not enough product sales data for this comparison."
    )

else:
    scatter_data["product_label"] = (
        scatter_data["source_stock_code"].astype(str)
        + " — "
        + scatter_data["product_name"].fillna("Unknown")
    )

    fig_scatter = px.scatter(
        scatter_data,
        x="units_sold",
        y="gross_sales",
        hover_name="product_label",
        size="gross_sales",
        labels={
            "units_sold": "Units Sold",
            "gross_sales": "Gross Sales",
        },
        template="plotly_dark",
        opacity=0.7,
    )

    fig_scatter.update_layout(
        height=450,
        margin=dict(l=10, r=10, t=20, b=10),
    )

    st.plotly_chart(
        fig_scatter,
        use_container_width=True,
    )


# -----------------------------
# Cancellation analysis
# -----------------------------

st.divider()

st.subheader("Top 10 products by cancellation value")

cancellation_products = (
    products[products["cancellation_value"] > 0]
    .nlargest(10, "cancellation_value")
    .copy()
)


if cancellation_products.empty:
    st.info(
        "No cancellation value found for this selection."
    )

else:
    cancellation_products["product_label"] = (
        cancellation_products["source_stock_code"].astype(str)
        + " — "
        + cancellation_products["product_name"].fillna("Unknown")
    )

    fig_cancellations = px.bar(
        cancellation_products.sort_values(
            "cancellation_value"
        ),
        x="cancellation_value",
        y="product_label",
        orientation="h",
        text="cancellation_value",
        labels={
            "cancellation_value": "Cancellation Value",
            "product_label": "Product",
        },
        template="plotly_dark",
    )

    fig_cancellations.update_traces(
        texttemplate="%{x:,.2f}",
        textposition="outside",
        cliponaxis=False,
        hovertemplate=(
            "%{y}<br>"
            "Cancellation value: %{x:,.2f}"
            "<extra></extra>"
        ),
    )

    fig_cancellations.update_layout(
        height=450,
        margin=dict(l=10, r=70, t=20, b=10),
    )

    st.plotly_chart(
        fig_cancellations,
        use_container_width=True,
    )


# -----------------------------
# Return quantity analysis
# -----------------------------

st.subheader("Top 10 products by returned units")

returned_products = (
    products[products["returned_units"] > 0]
    .nlargest(10, "returned_units")
    .copy()
)


if returned_products.empty:
    st.info(
        "No return quantities found for this selection."
    )

else:
    returned_products["product_label"] = (
        returned_products["source_stock_code"].astype(str)
        + " — "
        + returned_products["product_name"].fillna("Unknown")
    )

    fig_returns = px.bar(
        returned_products.sort_values("returned_units"),
        x="returned_units",
        y="product_label",
        orientation="h",
        text="returned_units",
        labels={
            "returned_units": "Returned Units",
            "product_label": "Product",
        },
        template="plotly_dark",
    )

    fig_returns.update_traces(
        texttemplate="%{x:,.0f}",
        textposition="outside",
        cliponaxis=False,
        hovertemplate=(
            "%{y}<br>"
            "Returned units: %{x:,.0f}"
            "<extra></extra>"
        ),
    )

    fig_returns.update_layout(
        height=450,
        margin=dict(l=10, r=70, t=20, b=10),
    )

    st.plotly_chart(
        fig_returns,
        use_container_width=True,
    )


# -----------------------------
# Detailed product table
# -----------------------------

st.divider()

st.subheader("Product performance table")

display_df = products[
    [
        "source_stock_code",
        "product_name",
        "gross_sales",
        "cancellation_value",
        "net_sales",
        "units_sold",
        "sales_invoices",
        "cancellation_lines",
        "returned_units",
        "return_lines",
    ]
].copy()


display_df = display_df.rename(
    columns={
        "source_stock_code": "Product Code",
        "product_name": "Product Name",
        "gross_sales": "Gross Sales",
        "cancellation_value": "Cancellation Value",
        "net_sales": "Net Sales After Cancellations",
        "units_sold": "Units Sold",
        "sales_invoices": "Sales Invoices",
        "cancellation_lines": "Cancellation Lines",
        "returned_units": "Returned Units",
        "return_lines": "Return Lines",
    }
)


display_df = display_df.sort_values(
    "Gross Sales",
    ascending=False,
)


st.dataframe(
    display_df,
    use_container_width=True,
    hide_index=True,
    column_config={
        "Gross Sales": st.column_config.NumberColumn(
            format="%,.2f"
        ),
        "Cancellation Value": st.column_config.NumberColumn(
            format="%,.2f"
        ),
        "Net Sales After Cancellations": (
            st.column_config.NumberColumn(
                format="%,.2f"
            )
        ),
        "Units Sold": st.column_config.NumberColumn(
            format="%,.0f"
        ),
        "Sales Invoices": st.column_config.NumberColumn(
            format="%,.0f"
        ),
        "Cancellation Lines": st.column_config.NumberColumn(
            format="%,.0f"
        ),
        "Returned Units": st.column_config.NumberColumn(
            format="%,.0f"
        ),
        "Return Lines": st.column_config.NumberColumn(
            format="%,.0f"
        ),
    },
)


# -----------------------------
# Download CSV
# -----------------------------

csv_data = display_df.to_csv(
    index=False
).encode("utf-8")


st.download_button(
    label="Download product analysis CSV",
    data=csv_data,
    file_name="retail360_product_analysis.csv",
    mime="text/csv",
)


# -----------------------------
# Footer
# -----------------------------

st.caption(
    "Retail360 Product Analysis · Local PostgreSQL data. "
    "Net Sales After Cancellations = Gross Sales minus "
    "recorded cancellation value. RETURN transactions "
    "currently have no monetary value in the source data."
)