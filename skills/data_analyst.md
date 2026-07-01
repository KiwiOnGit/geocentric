# Data Analysis & Visualisation Skill

## Purpose
Use this skill when processing CSV data, analyzing logs, aggregating statistics, running data algorithms, or plotting data distributions.

## 1. Core Directives
1. **Sanitise Before Processing**: Ensure null/empty values, broken lines, or improper formatting are cleaned or default-initialized before executing computation.
2. **Computational Security**: For large datasets, write streamlined Python scripts using pandas or numpy and execute them securely with `<run_file filename="..." />` or `<run_command>`.
3. **Structured Visualisations**: Whenever plotting tables or graphs, structure the outputs cleanly using markdown formatting, and ensure clear legend names, color maps, and axis labeling are established.

## 2. Structural Architecture
A data analysis workflow should always operate in these chronological steps:
```
[ 1. Ingest Data ] -> CSV/JSON reading, delimiter checks
         │
[ 2. Data Cleaning ] -> Deduplication, null interpolation, datatype casting
         │
[ 3. Computation ] -> Grouping, statistics, aggregations, ratios
         │
[ 4. Visualisation ] -> Plotting distributions, formatting markdown tables
```

## 3. High-Quality Code Examples

### CSV Ingestion, Grouping, & Clean Metrics Summary
```python
import pandas as pd
import json

def process_sales_metrics(csv_path: str, output_json: str):
    """
    Cleans a raw sales CSV dataset, calculates performance metrics, and exports reports.
    """
    try:
        # Ingestion with clean parsing
        df = pd.read_csv(csv_path)
        
        # Data cleaning: fill missing quantities with 0, convert cost to float
        df['Quantity'] = df['Quantity'].fillna(0).astype(int)
        df['Unit_Price'] = df['Unit_Price'].fillna(0.0).astype(float)
        
        # Computation: calculate revenue
        df['Revenue'] = df['Quantity'] * df['Unit_Price']
        
        # Aggregation: Group by category
        summary = df.groupby('Category').agg(
            total_items=('Quantity', 'sum'),
            total_revenue=('Revenue', 'sum'),
            average_price=('Unit_Price', 'mean')
        ).reset_index()
        
        # Visualisation / Export
        result = summary.to_dict(orientation="records")
        with open(output_json, "w") as f:
            json.dump(result, f, indent=2)
            
        print("[SUCCESS] Data successfully parsed and metrics aggregated.")
    except Exception as e:
        print(f"[ERROR] Sales processing failed: {str(e)}")
```
