# Retail360 --- Retail Sales Analytics Dashboard

Retail360 is a local-first retail analytics project that uses
PostgreSQL, SQL, Python, and Streamlit to explore sales performance and
product/customer/country trends.

> **Data validation note:** The dashboard currently calculates sales
> using `fact_sales.line_total` and `transaction_type`. Earlier analysis
> using `quantity * unit_price` produced a different total. Treat the
> dashboard totals as model-dependent until the two definitions are
> reviewed and documented consistently. Do not present the figures as
> independently reconciled business totals.

## Project goals

-   Organize retail transaction data into a relational PostgreSQL model.
-   Analyze sales, cancellations, products, customers, and countries.
-   Present key metrics and trends in an interactive Streamlit
    dashboard.
-   Practice data preparation, SQL aggregation, data modeling, and
    visualization.

## Technology stack

-   **Python** --- application logic
-   **Pandas** --- data handling
-   **PostgreSQL** --- relational data warehouse
-   **SQL** --- transformations, joins, aggregations, and analysis
-   **Streamlit** --- interactive dashboard
-   **Plotly** --- interactive charts

## Data source

The project uses `Online Retail.xlsx`, from the `Online Retail`
worksheet. The source workbook contains 541,909 rows.

The data is organized in PostgreSQL under the `retail360` schema. The
model includes:

-   `dim_country`
-   `dim_customer`
-   `dim_date`
-   `dim_product`
-   `fact_sales`

## Dashboard features

The current dashboard includes:

-   KPI cards for Gross Sales, Net Sales, Sales Invoices, and Units Sold
-   Monthly net sales trend
-   Monthly gross sales versus cancellations
-   Product analysis, including top products
-   Sales by country
-   Customer analysis
-   Date and country filtering (where configured in the app)

## Data preparation and quality

Product descriptions were reviewed and cleaned conservatively. Some
product names remain `Unknown` where the source data was missing or
ambiguous. These values should not be guessed or silently replaced; they
can be revisited if stronger source evidence becomes available.

## Sales metric definition

The current dashboard uses `fact_sales.line_total` grouped by
`transaction_type`:

-   **Gross Sales:** sum of `line_total` for `SALE` transactions
-   **Return Value:** absolute sum of `line_total` for `RETURN`
    transactions
-   **Cancellation Value:** absolute sum of `line_total` for
    `CANCELLATION` transactions
-   **Net Sales:** Gross Sales minus Return Value minus Cancellation
    Value

This definition should be kept consistent across KPI cards, charts,
exports, and written project findings. The project previously produced a
different total using `quantity * unit_price`; investigate the reason
for that difference before publishing numeric business conclusions.

## Database model

The schema follows a dimensional structure, with `fact_sales` connected
to dimensions such as date, product, customer, and country. The exact
foreign-key relationships and column definitions should be confirmed
from the database schema or SQL scripts before documenting them in more
detail.

## Run locally

1.  Install Python and PostgreSQL.

2.  Create or restore the `retail360` database and load the project
    tables.

3.  Open the project folder in a terminal.

4.  Install the dependencies used by the app. If the project has a
    `requirements.txt`, run:

    ``` bash
    pip install -r requirements.txt
    ```

    If no dependency file exists, create one from the packages imported
    by the app (for example, Streamlit, Pandas, Plotly, and the
    PostgreSQL driver actually used by the project).

5.  Start the dashboard:

    ``` bash
    streamlit run app.py
    ```

6.  Enter the local PostgreSQL connection details in the app's sidebar
    and connect to the warehouse.

> Keep database passwords out of source control. Use local secrets or
> environment variables where supported, and never commit credentials.

## Suggested repository structure

``` text
Retail360/
├── app.py
├── requirements.txt
├── README.md
├── sql/
│   └── *.sql
├── data/
│   └── (keep source data out of Git unless you have permission to share it)
└── screenshots/
    └── dashboard.png
```

Adjust this structure to match the files that actually exist in your
project.

## Portfolio screenshots

Add screenshots to a `screenshots/` folder and embed them here. For
example:

``` markdown
![Retail360 dashboard](screenshots/dashboard.png)
```

Recommended screenshots: 1. Sales Overview with KPI cards and monthly
charts 2. Product Analysis page 3. Country/customer analysis 4.
PostgreSQL dimensional schema or a clear schema diagram

## Future improvements

-   Standardize and document the sales metric definition across SQL and
    the dashboard.
-   Add automated data-quality checks and reconciliation tests.
-   Add a refresh/load workflow and document how to reproduce it.
-   Add tests for the main SQL queries and dashboard calculations.
-   Improve handling and review of unknown or ambiguous product names.
-   Add a concise business-insights section based on validated results.

## Project status

The local PostgreSQL warehouse and Streamlit dashboard are running.
Before publishing numeric findings, validate the sales definition and
reconcile the `line_total` and `quantity * unit_price` calculations.
