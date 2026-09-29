
from datetime import date

import pandas as pd
import plotly.express as px
import streamlit as st

from sqlalchemy import URL, bindparam, create_engine, text


# ============================================================
# Retail360 | Local Retail Analytics Dashboard
# ============================================================

st.set_page_config(
    page_title="Retail360 Analytics",
    page_icon="🛍️",
    layout="wide",
    initial_sidebar_state="expanded",
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
            padding: 18px 20px;
            border-radius: 14px;
        }

        div[data-testid="stMetricLabel"] {
            color: #aab7cc;
        }

        div[data-testid="stMetricValue"] {
            color: #ffffff;
        }

        section[data-testid="stSidebar"] {
            border-right: 1px solid #29344a;
        }

        .small-muted {
            color: #9aa8bd;
            font-size: 0.9rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


# -----------------------------
# Database connection
# -----------------------------

@st.cache_resource
def get_engine(host, port, database, username, password):
    connection_url = URL.create(
        drivername="postgresql+psycopg",
        username=username,
        password=password,
        host=host,
        port=int(port),
        database=database,
    )

    return create_engine(
        connection_url,
        pool_pre_ping=True,
        pool_size=3,
        max_overflow=2,
    )


def read_sql(engine, query, params=None, expanding=()):
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
# Sidebar
# -----------------------------

with st.sidebar:
    st.markdown("# 🛍️ Retail360")
    st.caption("Retail intelligence workspace")

    st.divider()
    st.subheader("Local database")

    db_host = st.text_input("Host", value="localhost")
    db_port = st.number_input(
        "Port",
        min_value=1,
        max_value=65535,
        value=5432,
    )
    db_name = st.text_input("Database", value="retail360")
    db_user = st.text_input("Username", value="postgres")
    db_password = st.text_input(
        "PostgreSQL password",
        type="password",
    )

    connect_clicked = st.button(
        "Connect to warehouse",
        type="primary",
        use_container_width=True,
    )

    if connect_clicked:
        if not db_password:
            st.error("Enter your PostgreSQL password.")
        else:
            st.session_state["db_config"] = {
                "host": db_host,
                "port": int(db_port),
                "database": db_name,
                "username": db_user,
                "password": db_password,
            }
            st.session_state.pop("connection_error", None)

    st.divider()
    st.caption("Runs locally on your computer.")
    st.caption("No cloud services required.")


# -----------------------------
# Require database connection
# -----------------------------

if "db_config" not in st.session_state:
    st.title("Retail360 Analytics")
    st.subheader("Your retail data. One clear view.")
    st.info(
        "Enter your local PostgreSQL credentials in the sidebar, "
        "then click **Connect to warehouse**."
    )

    st.markdown(
        """
        ### Your dashboard includes

        - Executive sales KPIs
        - Monthly sales and returns
        - Top-performing products
        - Country performance
        - Customer insights
        - Interactive date and country filters
        """
    )
    st.stop()


config = st.session_state["db_config"]

try:
    engine = get_engine(
        config["host"],
        config["port"],
        config["database"],
        config["username"],
        config["password"],
    )

    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))

except Exception as exc:
    st.error("Could not connect to PostgreSQL.")
    st.code(str(exc))
    st.info(
        "Check that PostgreSQL is running, the database name is "
        "retail360, and your username and password are correct."
    )
    st.stop()


# -----------------------------
# Load filter options
# -----------------------------

try:
    date_bounds = read_sql(
        engine,
        """
        SELECT
            MIN(d.full_date) AS min_date,
            MAX(d.full_date) AS max_date
        FROM retail360.fact_sales f
        JOIN retail360.dim_date d
            ON f.date_key = d.date_key
        """,
    )

    country_df = read_sql(
        engine,
        """
        SELECT DISTINCT co.country_name
        FROM retail360.fact_sales f
        JOIN retail360.dim_country co
            ON f.country_key = co.country_key
        WHERE co.country_name IS NOT NULL
        ORDER BY co.country_name
        """,
    )

    if date_bounds.empty or pd.isna(date_bounds.loc[0, "min_date"]):
        st.warning("The fact_sales table has no dated transactions yet.")
        st.stop()

    min_date = pd.to_datetime(date_bounds.loc[0, "min_date"]).date()
    max_date = pd.to_datetime(date_bounds.loc[0, "max_date"]).date()
    countries = country_df["country_name"].tolist()

except Exception as exc:
    st.error("Could not read Retail360 warehouse tables.")
    st.code(str(exc))
    st.stop()


# -----------------------------
# Dashboard filters
# -----------------------------

with st.sidebar:
    st.divider()
    st.subheader("Dashboard filters")

    selected_dates = st.date_input(
        "Transaction date range",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
    )

    selected_countries = st.multiselect(
        "Countries",
        options=countries,
        default=[],
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
    st.error("Start date must be before end date.")
    st.stop()


# -----------------------------
# SQL filter builder
# -----------------------------

def get_filter_sql():
    country_clause = ""

    params = {
        "start_date": start_date,
        "end_date": end_date,
    }

    expanding = []

    if selected_countries:
        country_clause = "AND co.country_name IN :countries"
        params["countries"] = selected_countries
        expanding.append("countries")

    return country_clause, params, expanding


country_clause, filter_params, expanding_params = get_filter_sql()


def query_filtered(sql):
    full_sql = sql.replace(
        "/* COUNTRY_FILTER */",
        country_clause,
    )

    return read_sql(
        engine,
        full_sql,
        params=filter_params,
        expanding=expanding_params,
    )


# All filtered queries join the date and country dimensions.
FILTER_JOINS = """
    FROM retail360.fact_sales f
    JOIN retail360.dim_date d
        ON f.date_key = d.date_key
    JOIN retail360.dim_country co
        ON f.country_key = co.country_key
    WHERE d.full_date >= :start_date
      AND d.full_date <= :end_date
      /* COUNTRY_FILTER */
"""


# -----------------------------
# Header
# -----------------------------

st.title("🛍️ Retail360 Analytics")
st.markdown(
    "Executive overview of sales, products, customers and returns."
)

st.caption(
    f"Reporting period: {start_date:%d %b %Y} – "
    f"{end_date:%d %b %Y}"
)

st.divider()


# -----------------------------
# KPI metrics
# -----------------------------

kpi_sql = f"""
    SELECT
        COALESCE(SUM(f.line_total) FILTER (
            WHERE f.transaction_type = 'SALE'
        ), 0) AS gross_sales,

        COALESCE(ABS(SUM(f.line_total) FILTER (
            WHERE f.transaction_type = 'RETURN'
        )), 0) AS return_value,

        COALESCE(ABS(SUM(f.line_total) FILTER (
            WHERE f.transaction_type = 'CANCELLATION'
        )), 0) AS cancellation_value,

        COUNT(DISTINCT f.invoice_no) FILTER (
            WHERE f.transaction_type = 'SALE'
        ) AS sales_invoices,

        COALESCE(SUM(f.quantity) FILTER (
            WHERE f.transaction_type = 'SALE'
        ), 0) AS units_sold

    {FILTER_JOINS}
"""

kpis = query_filtered(kpi_sql).iloc[0]

gross_sales = float(kpis["gross_sales"] or 0)
return_value = float(kpis["return_value"] or 0)
cancellation_value = float(kpis["cancellation_value"] or 0)
net_sales = gross_sales - return_value - cancellation_value
sales_invoices = int(kpis["sales_invoices"] or 0)
units_sold = int(kpis["units_sold"] or 0)

metric_cols = st.columns(4)
metric_cols[0].metric("Gross Sales", f"{gross_sales:,.2f}")
metric_cols[1].metric("Net Sales", f"{net_sales:,.2f}")
metric_cols[2].metric("Sales Invoices", f"{sales_invoices:,}")
metric_cols[3].metric("Units Sold", f"{units_sold:,}")


# -----------------------------
# Monthly sales trend
# -----------------------------

monthly_sql = f"""
    SELECT
        d.year_month,
        MIN(d.full_date) AS month_start,

        COALESCE(
            SUM(f.line_total) FILTER (
                WHERE f.transaction_type = 'SALE'
            ), 0
        ) AS gross_sales,

        COALESCE(
            ABS(SUM(f.line_total) FILTER (
                WHERE f.transaction_type = 'RETURN'
            )), 0
        ) AS return_value,

        COALESCE(
            ABS(SUM(f.line_total) FILTER (
                WHERE f.transaction_type = 'CANCELLATION'
            )), 0
        ) AS cancellation_value

    {FILTER_JOINS}

    GROUP BY d.year_month
    ORDER BY month_start
"""

monthly = query_filtered(monthly_sql)

if not monthly.empty:
    monthly["net_sales"] = (
        monthly["gross_sales"]
        - monthly["return_value"]
        - monthly["cancellation_value"]
    )

    monthly["month_start"] = pd.to_datetime(monthly["month_start"])

st.subheader("Sales performance over time")

if monthly.empty:
    st.info("No sales data is available for these filters.")
else:
    trend_col, compare_col = st.columns(2)

    with trend_col:
        st.markdown("#### Monthly net sales")
        fig_monthly = px.line(
            monthly,
            x="month_start",
            y="net_sales",
            markers=True,
            labels={
                "month_start": "Month",
                "net_sales": "Net Sales",
            },
            template="plotly_dark",
        )
        fig_monthly.update_layout(
            height=390,
            margin=dict(l=10, r=10, t=25, b=10),
            hovermode="x unified",
        )
        fig_monthly.update_traces(
            line=dict(width=3),
            hovertemplate="%{x|%b %Y}<br>Net sales: %{y:,.2f}<extra></extra>",
        )
        st.plotly_chart(fig_monthly, use_container_width=True)

    with compare_col:
        st.markdown("#### Gross sales vs. cancellations")
        monthly_compare = monthly.melt(
            id_vars=["year_month", "month_start"],
            value_vars=["gross_sales", "cancellation_value"],
            var_name="metric",
            value_name="amount",
        )
        monthly_compare["metric"] = monthly_compare["metric"].map({
            "gross_sales": "Gross Sales",
            "cancellation_value": "Cancellations",
        })
        fig_compare = px.bar(
            monthly_compare,
            x="year_month",
            y="amount",
            color="metric",
            barmode="group",
            labels={
                "year_month": "Month",
                "amount": "Value",
                "metric": "Metric",
            },
            template="plotly_dark",
        )
        fig_compare.update_layout(
            height=390,
            margin=dict(l=10, r=10, t=25, b=10),
            xaxis_tickangle=-35,
        )
        st.plotly_chart(fig_compare, use_container_width=True)


# -----------------------------
# Product and country charts
# -----------------------------

left_col, right_col = st.columns(2)

product_sql = f"""
    SELECT
        p.source_stock_code,
        p.product_name,

        COALESCE(
            SUM(f.line_total) FILTER (
                WHERE f.transaction_type = 'SALE'
            ), 0
        ) AS gross_sales,

        COALESCE(
            SUM(f.quantity) FILTER (
                WHERE f.transaction_type = 'SALE'
            ), 0
        ) AS units_sold

    {FILTER_JOINS}

    JOIN retail360.dim_product p
        ON f.product_key = p.product_key

    GROUP BY
        p.source_stock_code,
        p.product_name

    HAVING SUM(f.line_total) FILTER (
        WHERE f.transaction_type = 'SALE'
    ) IS NOT NULL

    ORDER BY gross_sales DESC
    LIMIT 10
"""

# The product dimension join must be part of the FROM clause.
product_sql = product_sql.replace(
    "/* COUNTRY_FILTER */",
    country_clause,
).replace(
    "    {FILTER_JOINS}",
    FILTER_JOINS.replace(
        "/* COUNTRY_FILTER */",
        country_clause,
    ).replace(
        "    JOIN retail360.dim_country co",
        "    JOIN retail360.dim_country co",
    ),
)

# Use a dedicated query to keep the joins unambiguous.
product_sql = f"""
    SELECT
        p.source_stock_code,
        p.product_name,

        COALESCE(
            SUM(f.line_total) FILTER (
                WHERE f.transaction_type = 'SALE'
            ), 0
        ) AS gross_sales,

        COALESCE(
            SUM(f.quantity) FILTER (
                WHERE f.transaction_type = 'SALE'
            ), 0
        ) AS units_sold

    FROM retail360.fact_sales f
    JOIN retail360.dim_date d
        ON f.date_key = d.date_key
    JOIN retail360.dim_country co
        ON f.country_key = co.country_key
    JOIN retail360.dim_product p
        ON f.product_key = p.product_key

    WHERE d.full_date >= :start_date
      AND d.full_date <= :end_date
      /* COUNTRY_FILTER */

    GROUP BY p.source_stock_code, p.product_name
    HAVING SUM(f.line_total) FILTER (
        WHERE f.transaction_type = 'SALE'
    ) IS NOT NULL
    ORDER BY gross_sales DESC
    LIMIT 10
"""

top_products = query_filtered(product_sql)

country_sql = f"""
    SELECT
        co.country_name,

        COALESCE(
            SUM(f.line_total) FILTER (
                WHERE f.transaction_type = 'SALE'
            ), 0
        ) AS gross_sales,

        COALESCE(
            SUM(f.quantity) FILTER (
                WHERE f.transaction_type = 'SALE'
            ), 0
        ) AS units_sold,

        COUNT(DISTINCT f.invoice_no) FILTER (
            WHERE f.transaction_type = 'SALE'
        ) AS invoices

    {FILTER_JOINS}

    GROUP BY co.country_name
    ORDER BY gross_sales DESC
    LIMIT 10
"""

country_performance = query_filtered(country_sql)

with left_col:
    st.subheader("Top 10 products")

    if top_products.empty:
        st.info("No product sales found.")
    else:
        top_products["product_label"] = (
            top_products["source_stock_code"].astype(str)
            + " — "
            + top_products["product_name"].fillna("Unknown")
        )

        fig_products = px.bar(
            top_products.sort_values("gross_sales"),
            x="gross_sales",
            y="product_label",
            orientation="h",
            labels={
                "gross_sales": "Gross Sales",
                "product_label": "Product",
            },
            template="plotly_dark",
        )

        fig_products.update_layout(
            height=430,
            margin=dict(l=10, r=10, t=20, b=10),
        )

        st.plotly_chart(
            fig_products,
            use_container_width=True,
        )

with right_col:
    st.subheader("Sales by country")

    if country_performance.empty:
        st.info("No country sales found.")
    else:
        fig_countries = px.bar(
            country_performance.sort_values("gross_sales"),
            x="gross_sales",
            y="country_name",
            orientation="h",
            labels={
                "gross_sales": "Gross Sales",
                "country_name": "Country",
            },
            template="plotly_dark",
        )

        fig_countries.update_layout(
            height=430,
            margin=dict(l=10, r=10, t=20, b=10),
        )

        st.plotly_chart(
            fig_countries,
            use_container_width=True,
        )


# -----------------------------
# Customer insights
# -----------------------------

st.divider()
st.subheader("Customer insights")

customer_sql = f"""
    SELECT
        c.source_customer_id,

        COUNT(DISTINCT f.invoice_no) FILTER (
            WHERE f.transaction_type = 'SALE'
        ) AS sales_invoices,

        COALESCE(
            SUM(f.line_total) FILTER (
                WHERE f.transaction_type = 'SALE'
            ), 0
        ) AS gross_sales,

        MAX(d.full_date) FILTER (
            WHERE f.transaction_type = 'SALE'
        ) AS last_purchase_date

    FROM retail360.fact_sales f
    JOIN retail360.dim_date d
        ON f.date_key = d.date_key
    JOIN retail360.dim_country co
        ON f.country_key = co.country_key
    JOIN retail360.dim_customer c
        ON f.customer_key = c.customer_key

    WHERE d.full_date >= :start_date
      AND d.full_date <= :end_date
      AND c.source_customer_id IS NOT NULL
      /* COUNTRY_FILTER */

    GROUP BY c.source_customer_id
    ORDER BY gross_sales DESC
    LIMIT 10
"""

top_customers = query_filtered(customer_sql)

if top_customers.empty:
    st.info("No identified customer sales found for these filters.")
else:
    display_customers = top_customers.rename(
        columns={
            "source_customer_id": "Customer ID",
            "sales_invoices": "Sales Invoices",
            "gross_sales": "Gross Sales",
            "last_purchase_date": "Last Purchase",
        }
    )

    display_customers["Gross Sales"] = display_customers[
        "Gross Sales"
    ].map(lambda value: f"{value:,.2f}")

    st.dataframe(
        display_customers,
        use_container_width=True,
        hide_index=True,
    )


# -----------------------------
# Returns and cancellations
# -----------------------------

st.divider()
st.subheader("Returns and cancellations")

returns_sql = f"""
    SELECT
        d.year_month,
        MIN(d.full_date) AS month_start,

        COUNT(*) FILTER (
            WHERE f.transaction_type = 'SALE'
        ) AS sale_lines,

        COUNT(*) FILTER (
            WHERE f.transaction_type = 'RETURN'
        ) AS return_lines,

        COUNT(*) FILTER (
            WHERE f.transaction_type = 'CANCELLATION'
        ) AS cancellation_lines,

        COALESCE(
            ABS(SUM(f.line_total) FILTER (
                WHERE f.transaction_type = 'RETURN'
            )), 0
        ) AS return_value

    {FILTER_JOINS}

    GROUP BY d.year_month
    ORDER BY month_start
"""

returns = query_filtered(returns_sql)

if not returns.empty:
    returns["return_rate"] = (
        returns["return_lines"]
        / returns["sale_lines"].replace(0, pd.NA)
        * 100
    )

    fig_returns = px.bar(
        returns,
        x="year_month",
        y="return_lines",
        labels={
            "year_month": "Month",
            "return_lines": "Return Lines",
        },
        template="plotly_dark",
    )

    fig_returns.update_layout(
        height=320,
        margin=dict(l=10, r=10, t=20, b=10),
    )

    st.plotly_chart(
        fig_returns,
        use_container_width=True,
    )

    st.dataframe(
        returns[
            [
                "year_month",
                "sale_lines",
                "return_lines",
                "cancellation_lines",
                "return_value",
                "return_rate",
            ]
        ].rename(
            columns={
                "year_month": "Month",
                "sale_lines": "Sale Lines",
                "return_lines": "Return Lines",
                "cancellation_lines": "Cancellation Lines",
                "return_value": "Return Value",
                "return_rate": "Return Lines / Sale Lines (%)",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )


# -----------------------------
# Footer
# -----------------------------

st.divider()

st.caption(
    "Retail360 · Local PostgreSQL warehouse · "
    "Net sales is calculated as gross sales less absolute return "
    "and cancellation values."
)

st.caption(
    "This dashboard runs locally. It does not publish data to the cloud."
)
