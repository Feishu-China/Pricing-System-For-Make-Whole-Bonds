# Pricing-System-For-Make-Whole-Bonds
A Python-based Make-Whole Bond Pricing Module.
## Overview
This Python script is a comprehensive financial tool designed to calculate the **Make-Whole call price** for bonds. The make-whole price is the present value of a bond's remaining cash flows, discounted at a rate equal to the prevailing U.S. Treasury yield plus a contractual Make-Whole spread. The tool dynamically sources benchmark rates from historical Treasury yield curves and implements precise financial mathematics for valuation.

## Key Features
*   **Treasury Curve Integration**: Loads and interpolates U.S. Treasury par yield curve data to serve as the base discount rate (`swap_rate` in the formula).
*   **Accurate Pricing Engine**: Core function (`calculate_makewhole_price_with_treasury`) strictly adheres to the standard financial formula, correctly handling periodicity and discounting.
*   **Bond Type Intelligence**: Automatically distinguishes and values:
    *   **Pure Make-Whole Bonds**: Discounts all remaining cash flows to the maturity date.
    *   **Blended Bonds (with Call Price)**: Discounts coupons to the first call date and the call price at that date.
*   **Flexible Analysis Modes**:
    *   **Batch Processing**: Calculate make-whole prices for an entire portfolio of bonds from a CSV file.
    *   **Single Bond Price Curve**: Generate a time-series of make-whole prices for a bond by shifting the calculation date (`curve` mode).
    *   **Blended Bond Call Curve**: For bonds with a call schedule, generate a price curve by simulating different potential call dates while keeping the calculation date fixed (`blendedcurve` mode).
*   **Robust Data Handling**: Includes fallback logic for missing data fields and proper conversion of market conventions (e.g., percentage prices).

## Core Algorithm
The calculation follows the standard present value formula for a make-whole call:

**P\_make-whole = Σ [ CF\_t+n / (1 + TreasuryRate\_t+n + MakeWholeSpread)^n ]**

Where:
*   `CF_t+n` = Cash flow (coupon or principal) at period `n`.
*   `TreasuryRate_t+n` = Interpolated Treasury yield for the specific cash flow's maturity.
*   `MakeWholeSpread` = Contractual make-whole premium (e.g., 0.0020 for 20 bps).
*   `n` = Period number (not years), using `period_years` for correct exponent application.

## Prerequisites
*   **Python 3.7+**
*   **Required Libraries**: Install via `pip install pandas numpy scipy`

## Installation & Setup
1.  **Clone or download** the script `MWBPS.py`.
2.  **Install dependencies**:
```bash
pip install pandas numpy scipy
```
3.  **Prepare your data files**:
*   Place your bond data CSV and Treasury curve CSV in the appropriate directory.
*   Update the file paths in the `main_treasury()` function within the script:
```python
input_file = r"PATH_TO_YOUR_BOND_DATA.csv"
treasury_file = r"PATH_TO_YOUR_TREASURY_CURVE.csv"
```
## Input File Formats
### 1. Bond Data File
A CSV file containing bond characteristics. **Mandatory columns** include:
*   `issue_id`: Unique bond identifier.
*   `coupon`: Annual coupon rate (e.g., 5.0 for 5%).
*   `principal_amt`: Face value/principal amount (e.g., 1000).
*   `calculation_date_s`: The date for which the price is calculated (YYYY-MM-DD).
*   `maturity_s`: Bond maturity date (YYYY-MM-DD).
*   `freq_numeric`: Coupon payment frequency per year (e.g., 2 for semi-annual).

**Highly Recommended columns**:
*   `period_years`: Length of one coupon period in years (e.g., 0.5 for semi-annual). **Critical for accurate discounting**.
*   `mw_decimal`: Make-Whole spread in decimal (e.g., 0.0020 for 20 bps).
*   `make_whole`: Indicator ('Y'/'N') if the bond has a make-whole provision.
*   `next_call_price`: Call price (in "per 100" format, e.g., 100.25) for blended bonds.
*   `first_call_date`: First eligible call date for blended bonds.
*   `first_interest_date_s`: Next coupon payment date after the calculation date.

### 2. Treasury Curve File (`par-yield-curve-rates-1990-2023.csv`)
A CSV file with historical U.S. Treasury par yields. Expected format includes a `date` column and rate columns for standard tenors (e.g., `1 mo`, `2 mo`, `3 mo`, `6 mo`, `1 yr`, `2 yr`, `3 yr`, `5 yr`, `7 yr`, `10 yr`, `20 yr`, `30 yr`). Rates should be in percentage terms (e.g., 3.85 for 3.85%).

## Usage
Run the script from the command line.

### Mode 1: Batch Pricing (Default)
Calculates make-whole prices for all bonds in the input file.
```bash
python MWBPS.py
```
**Output**: A CSV file named `makewhole_prices_treasury_method_fixed_with_spread.csv` containing the calculated price (`makewhole_price`, `price_per_100`) and spread (`spread`) for each bond.

### Mode 2: Single Bond Price Curve
Generates a price curve for a specific bond by simulating different calculation dates (e.g., monthly from the make-whole start to end date).
```bash
python MWBPS.py curve <issue_id>
```
```bash
python MWBPS.py curve 627513
```
**Output**: A CSV file named `makewhole_curve_<issue_id>.csv` with prices over time.

### Mode 3: Blended Bond Call Curve Analysis
For a blended bond, generates a price curve by simulating different potential call dates (keeping the calculation date fixed at the make-whole start date).
```bash
python MWBPS.py blendedcurve <issue_id>
```
```bash
python MWBPS.py blendedcurve 627513
```
**Output**: A CSV file named `blended_bond_curve_<issue_id>.csv` with prices for each simulated call date.

## Output Description
The primary outputs are CSV files containing:

*   **Batch Mode Output**:
    *   `issue_id`, `coupon`, `principal_amt`: Bond identifiers and terms.
    *   `make_whole_type`: 'Pure' or 'Blended'.
    *   `makewhole_price`: The calculated make-whole price in absolute currency.
    *   `price_per_100`: The make-whole price per 100 of face value.
    *   `spread`: The resulting yield spread (Coupon Rate - (Treasury Rate + MW Spread)).

*   **Curve Analysis Outputs**:
    *   For `curve` mode: `calculation_date`, `remaining_years`, `price_per_100`, `spread`.
    *   For `blendedcurve` mode: `call_date`, `years_to_call`, `price_per_100`, `spread`.

## Important Notes
*   The script expects the `next_call_price` field in the bond data to be in **"per 100" format** (e.g., 100.25) and handles the conversion to a cash amount (`principal * next_call_price / 100`).
*   The calculation of the first interest payment date is robust: if `first_interest_date_s` is not provided or is on/before the calculation date, the script will project it forward based on the coupon frequency (`freq_numeric`).
*   The `period_years` field in the bond data is **critical** for accurate discounting. If missing, it is derived from `1 / freq_numeric`.

## Use Case Guidance
*   **Portfolio Valuation**: Use **Batch Mode** to value a large set of bonds containing make-whole provisions on a specific calculation date.
*   **Historical Analysis / Backtesting**: Use **Mode 2 (`curve`)** for a single bond to see how its make-whole price would have fluctuated over a historical period based on changing Treasury rates.
*   **Call Strategy Analysis (for Callable Bonds)**: Use **Mode 3 (`blendedcurve`)** to understand how the make-whole call price for a blended bond varies as its call date approaches, aiding in redemption decision analysis.

## Code Structure
*   `TreasuryCurveProvider` Class: Manages yield curve data loading, caching, and interpolation.
*   `calculate_makewhole_price_with_treasury()`: The core pricing function.
*   `calculate_makewhole_batch_treasury()`: Orchestrates batch processing.
*   `calculate_makewhole_curve_for_bond()` / `calculate_blended_bond_price_curve()`: Generate time-series and call-date-series analyses.
*   `main_treasury()`: Main function handling command-line arguments and execution flow.
