import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
from scipy.interpolate import interp1d
from math import ceil
import sys

warnings.filterwarnings('ignore')


class TreasuryCurveProvider:
    """
    Treasury Yield Curve Provider
    Responsible for loading, managing, and providing Treasury yield curve data
    """

    def __init__(self, treasury_file_path):
        """
        Initialize Treasury Curve Provider
        Parameters:
        treasury_file_path: Path to the Treasury yield curve data file
        """

        self.treasury_curve = None
        self.term_mapping = {}
        self.interpolation_cache = {}
        self.load_treasury_data(treasury_file_path)

    def load_treasury_data(self, file_path):
        """
        Load Treasury Yield Curve Data

        Data format: date, 1 mo, 2 mo, 3 mo, 4 mo, 6 mo, 1 yr, 2 yr, 3 yr, 5 yr, 7 yr, 10 yr, 20 yr, 30 yr
        """
        print(f"Loading Treasury Yield Curve Data: {file_path}")

        # read data
        df = pd.read_csv(file_path, parse_dates=['date'])

        # Set date index and sort
        df.set_index('date', inplace=True)
        df.sort_index(inplace=True)

        # Convert percentages to decimals (e.g., 7.83 -> 0.0783)
        rate_columns = ['1 mo', '2 mo', '3 mo', '4 mo', '6 mo',
                        '1 yr', '2 yr', '3 yr', '5 yr', '7 yr',
                        '10 yr', '20 yr', '30 yr']

        for col in rate_columns:
            if col in df.columns:
                # Replace empty strings with NaN, then convert to numeric
                df[col] = pd.to_numeric(df[col], errors='coerce') / 100.0

        # fill nans
        df = df.ffill()

        # rename col
        column_mapping = {
            '1 mo': 'rate_1m', '2 mo': 'rate_2m', '3 mo': 'rate_3m',
            '4 mo': 'rate_4m', '6 mo': 'rate_6m', '1 yr': 'rate_1y',
            '2 yr': 'rate_2y', '3 yr': 'rate_3y', '5 yr': 'rate_5y',
            '7 yr': 'rate_7y', '10 yr': 'rate_10y', '20 yr': 'rate_20y',
            '30 yr': 'rate_30y'
        }

        df = df.rename(columns=column_mapping)
        self.treasury_curve = df

        # Build term mapping (term -> number of years)
        self.term_mapping = {
            'rate_1m': 1 / 12,
            'rate_2m': 2 / 12,
            'rate_3m': 3 / 12,
            'rate_4m': 4 / 12,
            'rate_6m': 6 / 12,
            'rate_1y': 1.0,
            'rate_2y': 2.0,
            'rate_3y': 3.0,
            'rate_5y': 5.0,
            'rate_7y': 7.0,
            'rate_10y': 10.0,
            'rate_20y': 20.0,
            'rate_30y': 30.0
        }

        print(f"Data loading completed: {df.shape[0]} trading days")
        print(f"Data time range: {df.index.min().date()} to {df.index.max().date()}")

    def get_rate(self, target_date, term_years, method='linear'):
        """
        Get Treasury yield for specified date and term

        Parameters:
            target_date: Target date
            term_years: Term (in years)
            method: Interpolation method ('linear', 'cubic', 'previous', 'next')
        """
        # checking cache
        cache_key = f"{target_date.strftime('%Y%m%d')}_{method}"
        if cache_key in self.interpolation_cache:
            interp_func = self.interpolation_cache[cache_key]
        else:
            # Get the yield curve for this date
            try:
                date_series = self.treasury_curve.loc[target_date]
            except KeyError:
                # If the date is not in the data, find the nearest date
                try:
                    # Find the nearest previous date
                    nearest_date = self.treasury_curve.index[self.treasury_curve.index <= target_date].max()
                    date_series = self.treasury_curve.loc[nearest_date]
                except:
                    # If it still fails, use the average curve
                    date_series = self.treasury_curve.iloc[-1]

            # Extract term and yield
            terms = []
            rates = []
            for col, term in self.term_mapping.items():
                if col in date_series.index:
                    terms.append(term)
                    rates.append(date_series[col])

            if len(terms) < 2:

                if term_years <= 0.5:
                    return 0.02
                elif term_years <= 5:
                    return 0.03
                else:
                    return 0.04

            # Create interpolation function
            interp_func = interp1d(terms, rates, kind=method, fill_value='extrapolate')
            self.interpolation_cache[cache_key] = interp_func

        # Use interpolation function to obtain yield for specified term
        rate = float(interp_func(term_years))
        return max(0.001, min(0.20, rate))


def calculate_makewhole_price_with_treasury(row, treasury_provider):
    """
    Calculate Make-Whole execution price using Treasury yield curve
    P{i,t}^{make-whole call} = Σ{n=1}^N [CF{i,t+n} / (1 + swap_rate{i,t+n} + make_whole_premium_i)^n]

    Parameters:
    - row: Bond data row (must contain period_years field)
    - treasury_provider: TreasuryCurveProvider instance

    Returns:
    - (Make-Whole execution price, spread)
    """
    try:

        principal = float(row.get('principal_amt', 1000))
        coupon_rate = float(row.get('coupon', 5.0)) / 100.0


        if pd.notna(row.get('freq_numeric', np.nan)):
            freq = int(row['freq_numeric'])
        elif pd.notna(row.get('coupon_freq', np.nan)):

            freq_str = str(row['coupon_freq'])
            if 'SEMI' in freq_str.upper():
                freq = 2
            elif 'QUARTER' in freq_str.upper():
                freq = 4
            elif 'MONTH' in freq_str.upper():
                freq = 12
            else:
                freq = 1
        else:
            freq = 2


        if pd.notna(row.get('period_years', np.nan)):
            period_years = float(row['period_years'])
        else:

            period_years = 1.0 / freq


        if pd.notna(row.get('mw_decimal', np.nan)):
            mw_premium = float(row['mw_decimal'])
        elif pd.notna(row.get('make_whole_spread_bps', np.nan)):
            mw_premium = float(row['make_whole_spread_bps']) / 10000.0
        else:
            mw_premium = 0.0


        is_blended = False


        make_whole_value = str(row.get('make_whole', 'N')).upper()

        if make_whole_value == 'Y' and pd.notna(row.get('next_call_price', np.nan)):
            is_blended = True



            next_call_price_pct = float(row['next_call_price'])
            final_payment = principal * next_call_price_pct / 100.0



            if pd.notna(row.get('first_call_date', np.nan)):
                try:

                    end_date = pd.to_datetime(row['first_call_date'])
                except:

                    if pd.notna(row.get('call_period_years', np.nan)):
                        temp_start_date = pd.to_datetime(row['calculation_date_s'])
                        end_date = temp_start_date + pd.DateOffset(years=int(row['call_period_years']))
                    else:
                        end_date = pd.to_datetime(row['maturity_s'])
            else:
                end_date = pd.to_datetime(row['maturity_s'])
        else:

            is_blended = False
            final_payment = principal
            end_date = pd.to_datetime(row['maturity_s'])


        start_date = pd.to_datetime(row['calculation_date_s'])


        if pd.notna(row.get('first_interest_date_s', np.nan)):
            first_payment_date = pd.to_datetime(row['first_interest_date_s'])
        elif pd.notna(row.get('dated_date_s', np.nan)):
            first_payment_date = pd.to_datetime(row['dated_date_s'])
        else:

            first_payment_date = start_date


        while first_payment_date <= start_date:
            months_to_add = 12 // freq
            if months_to_add == 0:
                months_to_add = 12

            new_month = first_payment_date.month + months_to_add
            new_year = first_payment_date.year
            while new_month > 12:
                new_year += 1
                new_month -= 12

            try:
                first_payment_date = datetime(new_year, new_month, first_payment_date.day)
            except ValueError:
                first_payment_date = datetime(new_year, new_month, 28)


        periods = []
        current_date = first_payment_date
        period_count = 0


        while current_date < end_date:
            period_count += 1
            n = period_count


            years_from_start = (current_date - start_date).days / 365.25


            treasury_rate = treasury_provider.get_rate(start_date, years_from_start)


            if treasury_rate is None:
                treasury_rate = 0.03


            annual_discount_rate = treasury_rate + mw_premium
            annual_discount_rate = max(0.001, min(0.20, annual_discount_rate))


            period_discount_rate = annual_discount_rate * period_years



            cashflow = principal * coupon_rate / freq


            discount_factor = 1 / ((1 + period_discount_rate) ** n)

            periods.append({
                'period': n,
                'date': current_date,
                'years_from_start': years_from_start,
                'cashflow': cashflow,  # CF_{i,t+n}
                'treasury_rate': treasury_rate,  # swap_rate_{i,t+n}
                'mw_premium': mw_premium,  # make_whole_premium_i
                'annual_discount_rate': annual_discount_rate,
                'period_discount_rate': period_discount_rate,
                'discount_factor': discount_factor,
                'pv_cashflow': cashflow * discount_factor  # CF_{i,t+n} / (1 + r)^n
            })


            months_to_add = 12 // freq
            if months_to_add == 0:
                months_to_add = 12


            new_month = current_date.month + months_to_add
            new_year = current_date.year
            while new_month > 12:
                new_year += 1
                new_month -= 12


            try:
                current_date = datetime(new_year, new_month, current_date.day)
            except ValueError:
                current_date = datetime(new_year, new_month, 28)


        final_years = (end_date - start_date).days / 365.25


        final_treasury_rate = treasury_provider.get_rate(start_date, final_years)
        if final_treasury_rate is None:
            final_treasury_rate = 0.03

        final_annual_discount_rate = final_treasury_rate + mw_premium
        final_annual_discount_rate = max(0.001, min(0.20, final_annual_discount_rate))



        if period_years > 0:

            final_n = ceil(final_years / period_years)

            final_n = max(period_count, final_n)
        else:
            final_n = period_count + 1

        final_period_discount_rate = final_annual_discount_rate * period_years
        final_discount_factor = 1 / ((1 + final_period_discount_rate) ** final_n)
        pv_final = final_payment * final_discount_factor


        total_pv = sum([p['pv_cashflow'] for p in periods]) + pv_final



        weighted_sum = sum(p['treasury_rate'] * p['pv_cashflow'] for p in periods) + final_treasury_rate * pv_final
        weighted_avg_treasury_rate = weighted_sum / total_pv if total_pv != 0 else 0


        spread = coupon_rate - (weighted_avg_treasury_rate + mw_premium)

        return total_pv, spread

    except Exception as e:
        print(f"ERROR {row.get('issue_id', 'unknown')}: {str(e)}")
        return np.nan, np.nan



def calculate_makewhole_batch_treasury(df, treasury_provider):
    """
    Calculate Make-Whole prices in batch using Treasury yield curve

    Parameters:
    - df: Bond data DataFrame
    - treasury_provider: TreasuryCurveProvider instance

    Returns:
    - Result DataFrame containing prices and spreads
    """
    results = []


    if 'period_years' not in df.columns:
        print("Warning: Dataset missing 'period_years' field, will estimate using freq_numeric")


    if 'first_interest_date_s' not in df.columns:
        print("Warning: Dataset missing 'first_interest_date_s' field, will estimate coupon payment dates using alternative methods")


    for idx, row in df.iterrows():
        price, spread = calculate_makewhole_price_with_treasury(row, treasury_provider)


        issue_id = row.get('issue_id', f'unknown_{idx}')
        coupon = row.get('coupon', np.nan)
        principal_amt = row.get('principal_amt', np.nan)
        mw_decimal = row.get('mw_decimal', np.nan)
        freq_numeric = row.get('freq_numeric', np.nan)
        period_years = row.get('period_years', np.nan)


        make_whole_value = str(row.get('make_whole', 'N')).upper()
        has_next_call_price = pd.notna(row.get('next_call_price', np.nan))

        if make_whole_value == 'Y' and has_next_call_price:
            make_whole_type = 'Blended'
        else:
            make_whole_type = 'Pure'


        if pd.notna(price) and pd.notna(principal_amt) and float(principal_amt) > 0:
            price_per_100 = (price / float(principal_amt)) * 100
        else:
            price_per_100 = np.nan

        results.append({
            'issue_id': issue_id,
            'coupon': coupon,
            'principal_amt': principal_amt,
            'mw_decimal': mw_decimal,
            'freq_numeric': freq_numeric,
            'period_years': period_years,
            'make_whole_type': make_whole_type,
            'makewhole_price': price,
            'price_per_100': price_per_100,
            'spread': spread
        })


        if (idx + 1) % 100 == 0:
            print(f"Calculated {idx + 1}/{len(df)} bonds")

    return pd.DataFrame(results)



def calculate_blended_bond_price_curve(issue_id, df, treasury_provider, step_days=30):
    """
    Calculate price curve for blended bonds (for cases lacking call schedule)

    Functionality:
    1. Use next_call_date as the first call date
    2. Calculate prices at one-month intervals from the first call date to maturity
    3. Price calculation date fixed as the first day of Make-Whole (mw_start_s)

    Parameters:
    - issue_id: Bond ID
    - df: Bond data DataFrame
    - treasury_provider: TreasuryCurveProvider instance
    - step_days: Calculation step (in days), default 30 days (monthly)

    Returns:
    - DataFrame containing price curve
    """
    print(f"Starting to calculate price curve for blended bond {issue_id}...")


    bond_row = df[df['issue_id'] == issue_id]
    if len(bond_row) == 0:
        print(f"Error: Bond with issue_id {issue_id} not found")
        return None


    original_row = bond_row.iloc[0].copy()


    make_whole_value = str(original_row.get('make_whole', 'N')).upper()
    has_next_call_price = pd.notna(original_row.get('next_call_price', np.nan))

    if not (make_whole_value == 'Y' and has_next_call_price):
        print(f"Error: Bond {issue_id} is not a blended bond (make_whole='Y' and next_call_price exists)")
        return None


    if pd.notna(original_row.get('mw_start_s', np.nan)):
        calculation_date = pd.to_datetime(original_row['mw_start_s'])
        print(f"Using Make-Whole start date as calculation reference date: {calculation_date.date()}")
    else:

        calculation_date = pd.to_datetime(original_row['calculation_date_s'])
        print(f"Warning: Missing mw_start_s field, using calculation_date_s: {calculation_date.date()}")


    if pd.notna(original_row.get('next_call_date', np.nan)):
        first_call_date = pd.to_datetime(original_row['next_call_date'])
        print(f"Using next_call_date as the first call date: {first_call_date.date()}")
    elif pd.notna(original_row.get('first_call_date', np.nan)):
        first_call_date = pd.to_datetime(original_row['first_call_date'])
        print(f"Warning: Missing next_call_date field, using first_call_date: {first_call_date.date()}")
    elif pd.notna(original_row.get('call_period_years', np.nan)):

        call_period_years = int(original_row['call_period_years'])
        first_call_date = calculation_date + pd.DateOffset(years=call_period_years)
        print(f"Warning: Missing next_call_date and first_call_date fields, calculating using call_period_years: {first_call_date.date()}")
    else:
        print(f"Error: Unable to determine the first call date, missing next_call_date/first_call_date/call_period_years fields")
        return None


    maturity_date = pd.to_datetime(original_row['maturity_s'])


    if first_call_date >= maturity_date:
        print(f"Error: First call date ({first_call_date.date()}) is later than or equal to maturity date ({maturity_date.date()})")
        return None

    print(f"Price calculation date (fixed): {calculation_date.date()}")
    print(f"First call date: {first_call_date.date()}")
    print(f"maturity date: {maturity_date.date()}")
    print(f"calculated step_days: {step_days} 天")


    call_dates = []
    current_date = first_call_date
    while current_date <= maturity_date:
        call_dates.append(current_date)
        current_date += timedelta(days=step_days)


    if call_dates[-1] != maturity_date:
        call_dates.append(maturity_date)

    print(f"{len(call_dates)} call dates generated")


    results = []

    for i, call_date in enumerate(call_dates):

        row_copy = original_row.copy()


        row_copy['calculation_date_s'] = calculation_date


        row_copy['first_call_date'] = call_date


        price, spread = calculate_makewhole_price_with_treasury(row_copy, treasury_provider)


        principal_amt = float(original_row.get('principal_amt', 1000))
        if pd.notna(price) and principal_amt > 0:
            price_per_100 = (price / principal_amt) * 100
        else:
            price_per_100 = np.nan


        years_to_call = (call_date - calculation_date).days / 365.25


        years_to_maturity = (maturity_date - calculation_date).days / 365.25

        results.append({
            'call_date': call_date,
            'years_to_call': years_to_call,
            'years_to_maturity': years_to_maturity,
            'makewhole_price': price,
            'price_per_100': price_per_100,
            'spread': spread,
            'calculation_date': calculation_date,
            'treasury_rate_date': calculation_date,
        })


        if (i + 1) % 10 == 0 or (i + 1) == len(call_dates):
            print(f" Progress: {i + 1}/{len(call_dates)} - call_date: {call_date.date()}, price: {price_per_100:.2f}")


    curve_df = pd.DataFrame(results)


    curve_df['issue_id'] = issue_id
    curve_df['coupon'] = original_row.get('coupon', np.nan)
    curve_df['principal_amt'] = original_row.get('principal_amt', np.nan)
    curve_df['maturity_date'] = maturity_date
    curve_df['next_call_price'] = original_row.get('next_call_price', np.nan)
    curve_df['freq_numeric'] = original_row.get('freq_numeric', np.nan)
    curve_df['mw_decimal'] = original_row.get('mw_decimal', np.nan)
    curve_df['calculation_date_fixed'] = calculation_date


    cols = ['issue_id', 'calculation_date_fixed', 'call_date',
            'years_to_call', 'years_to_maturity',
            'makewhole_price', 'price_per_100', 'spread',
            'coupon', 'principal_amt', 'maturity_date',
            'next_call_price', 'freq_numeric', 'mw_decimal',
            'treasury_rate_date']

    curve_df = curve_df[[c for c in cols if c in curve_df.columns]]

    return curve_df



def calculate_makewhole_curve_for_bond(issue_id, df, treasury_provider, step_days=30):
    """
    Calculate Make-Whole price curve for a specified bond

    Since the Make-Whole call schedule is uncertain, we calculate prices for all
    possible call dates from the Make-Whole start date to the end date,
    forming a price curve.

    Parameters:
    - issue_id: Bond ID
    - df: Bond data DataFrame
    - treasury_provider: TreasuryCurveProvider instance
    - step_days: Calculation step (in days), default 30 days (monthly)

    Returns:
    - DataFrame containing price curve
    """
    print(f"Starting to calculate Make-Whole price curve for bond {issue_id}...")


    bond_row = df[df['issue_id'] == issue_id]
    if len(bond_row) == 0:
        print(f"Error: Bond with issue_id {issue_id} not found")
        return None


    original_row = bond_row.iloc[0].copy()



    if pd.notna(original_row.get('mw_start_s', np.nan)):
        start_range = pd.to_datetime(original_row['mw_start_s'])
    else:

        start_range = pd.to_datetime(original_row['calculation_date_s'])

    if pd.notna(original_row.get('mw_end_s', np.nan)):
        end_range = pd.to_datetime(original_row['mw_end_s'])
    else:

        end_range = pd.to_datetime(original_row['maturity_s'])


    if start_range > end_range:
        start_range, end_range = end_range, start_range

    print(f"Calculation date range: {start_range.date()} to {end_range.date()}")
    print(f"Calculation step: {step_days} days")


    calculation_dates = []
    current_date = start_range
    while current_date <= end_range:
        calculation_dates.append(current_date)
        current_date += timedelta(days=step_days)


    if calculation_dates[-1] != end_range:
        calculation_dates.append(end_range)

    print(f"Generated {len(calculation_dates)} calculation dates")


    results = []

    for i, calc_date in enumerate(calculation_dates):

        row_copy = original_row.copy()
        row_copy['calculation_date_s'] = calc_date


        price, spread = calculate_makewhole_price_with_treasury(row_copy, treasury_provider)

        principal_amt = float(original_row.get('principal_amt', 1000))
        if pd.notna(price) and principal_amt > 0:
            price_per_100 = (price / principal_amt) * 100
        else:
            price_per_100 = np.nan


        maturity_date = pd.to_datetime(original_row['maturity_s'])
        remaining_years = (maturity_date - calc_date).days / 365.25

        results.append({
            'calculation_date': calc_date,
            'makewhole_price': price,
            'price_per_100': price_per_100,
            'spread': spread,
            'remaining_years': remaining_years,
            'treasury_rate_date': calc_date,
        })


        if (i + 1) % 10 == 0 or (i + 1) == len(calculation_dates):
            print(f" Progress: {i + 1}/{len(calculation_dates)} - Date: {calc_date.date()}, Price: {price_per_100:.2f}")


    curve_df = pd.DataFrame(results)


    curve_df['issue_id'] = issue_id
    curve_df['coupon'] = original_row.get('coupon', np.nan)
    curve_df['principal_amt'] = original_row.get('principal_amt', np.nan)
    curve_df['maturity_date'] = pd.to_datetime(original_row['maturity_s'])
    curve_df['freq_numeric'] = original_row.get('freq_numeric', np.nan)
    curve_df['mw_decimal'] = original_row.get('mw_decimal', np.nan)


    cols = ['issue_id', 'calculation_date', 'remaining_years',
            'makewhole_price', 'price_per_100', 'spread',
            'coupon', 'principal_amt', 'maturity_date',
            'freq_numeric', 'mw_decimal', 'treasury_rate_date']

    curve_df = curve_df[[c for c in cols if c in curve_df.columns]]

    return curve_df



def main_treasury():

    input_file = r"data\bond_data.csv"
    treasury_file = r"data\par-yield-curve-rates-1990-2023.csv"

    try:
        df = pd.read_csv(input_file, low_memory=False)
        print(f"Successfully loaded bond data: {len(df)} rows")


        print(f"Bond data column names: {df.columns.tolist()}")


        required_fields = ['principal_amt', 'coupon', 'calculation_date_s', 'maturity_s', 'freq_numeric']
        missing_fields = [field for field in required_fields if field not in df.columns]

        if missing_fields:
            print(f"Warning: The following required fields are missing: {missing_fields}")
            print("Will continue calculation using default values")

    except Exception as e:
        print(f"Failed to load bond data: {str(e)}")
        return


    try:
        treasury_provider = TreasuryCurveProvider(treasury_file)
    except Exception as e:
        print(f"Failed to load Treasury yield curve: {str(e)}")

        return


    date_columns = ['calculation_date_s', 'maturity_s', 'first_call_date',
                    'first_interest_date_s', 'dated_date_s', 'mw_start_s', 'mw_end_s', 'next_call_date']

    for col in date_columns:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors='coerce')
            valid_dates = df[col].notna().sum()
            print(f"Converting date field {col}: {valid_dates}/{len(df)} valid values")


    if len(sys.argv) > 1:
        if sys.argv[1] == 'curve':

            if len(sys.argv) > 2:
                issue_id = sys.argv[2]
                try:

                    issue_id = int(issue_id)
                except:
                    pass


                curve_df = calculate_makewhole_curve_for_bond(issue_id, df, treasury_provider, step_days=30)

                if curve_df is not None:

                    output_file = f"makewhole_curve_{issue_id}.csv"
                    curve_df.to_csv(output_file, index=False)
                    print(f"\nPrice curve for bond {issue_id} has been saved to: {output_file}")


                    print("\nPrice curve summary:")
                    print(
                        f"- Calculation date range: {curve_df['calculation_date'].min().date()} to {curve_df['calculation_date'].max().date()}")
                    print(
                        f"- Price range (per 100): {curve_df['price_per_100'].min():.2f} to {curve_df['price_per_100'].max():.2f}")
                    print(f"- Average price (per 100): {curve_df['price_per_100'].mean():.2f}")
                    print(
                        f"- Remaining term range: {curve_df['remaining_years'].min():.2f} to {curve_df['remaining_years'].max():.2f} years")
                    print(
                        f"- Spread range: {curve_df['spread'].min():.4f} ({curve_df['spread'].min() * 100:.2f}%) to {curve_df['spread'].max():.4f} ({curve_df['spread'].max() * 100:.2f}%)")

                    # Display first 5 rows
                    print("\nPrices for first 5 calculation points:")
                    print(curve_df.head(5).to_string())
            else:
                print("Error: Curve calculation mode requires issue_id to be specified")
                print("Usage: python MWBPS.py curve <issue_id>")
                print("\nExample: python MWBPS.py curve 627513")

                # Display first 10 bond issue_ids for reference
                if 'issue_id' in df.columns:
                    print("\nAvailable bond issue_ids (first 10):")
                    print(df['issue_id'].head(10).tolist())
                return

        elif sys.argv[1] == 'blendedcurve':

            if len(sys.argv) > 2:
                issue_id = sys.argv[2]
                try:

                    issue_id = int(issue_id)
                except:
                    pass


                curve_df = calculate_blended_bond_price_curve(issue_id, df, treasury_provider, step_days=30)

                if curve_df is not None:

                    output_file = f"blended_bond_curve_{issue_id}.csv"
                    curve_df.to_csv(output_file, index=False)

                    print(f"\nPrice curve for blended bond {issue_id} has been saved to: {output_file}")

                    # Display summary statistics
                    print("\nBlended bond price curve summary:")
                    print(f"- Fixed calculation reference date: {curve_df['calculation_date_fixed'].iloc[0].date()}")
                    print(
                        f"- Call date range: {curve_df['call_date'].min().date()} to {curve_df['call_date'].max().date()}")
                    print(
                        f"- Price range (per 100): {curve_df['price_per_100'].min():.2f} to {curve_df['price_per_100'].max():.2f}")
                    print(f"- Average price (per 100): {curve_df['price_per_100'].mean():.2f}")
                    print(
                        f"- Call term range: {curve_df['years_to_call'].min():.2f} to {curve_df['years_to_call'].max():.2f} years")
                    print(
                        f"- Total remaining term range: {curve_df['years_to_maturity'].min():.2f} to {curve_df['years_to_maturity'].max():.2f} years")
                    print(
                        f"- Spread range: {curve_df['spread'].min():.4f} ({curve_df['spread'].min() * 100:.2f}%) to {curve_df['spread'].max():.4f} ({curve_df['spread'].max() * 100:.2f}%)")

                    # Display first 10 rows
                    print("\nPrices for first 10 call dates:")
                    print(curve_df.head(10).to_string())


                    if len(curve_df) > 1:
                        price_change = curve_df['price_per_100'].iloc[-1] - curve_df['price_per_100'].iloc[0]
                    print(f"\nPrice trend analysis:")
                    print(f"- From the first call date to the last call date, price change: {price_change:.2f}")
                    print(f"- Average monthly price change: {price_change / len(curve_df):.2f}")

                    # Find lowest price point
                    min_price_idx = curve_df['price_per_100'].idxmin()
                    min_price_row = curve_df.loc[min_price_idx]
                    print(
                        f"- Lowest price point: {min_price_row['call_date'].date()}, price: {min_price_row['price_per_100']:.2f}")

                    # Find highest price point
                    max_price_idx = curve_df['price_per_100'].idxmax()
                    max_price_row = curve_df.loc[max_price_idx]
                    print(
                        f"- Highest price point: {max_price_row['call_date'].date()}, price: {max_price_row['price_per_100']:.2f}")
            else:
                print("Error: blendedcurve mode requires issue_id to be specified")
                print("Usage: python MWBPS.py blendedcurve <issue_id>")
                print("\nExample: python MWBPS.py blendedcurve 627513")

                # Display Blended bond issue_ids for reference
                if 'issue_id' in df.columns and 'make_whole' in df.columns and 'next_call_price' in df.columns:
                    blended_bonds = df[(df['make_whole'] == 'Y') & (df['next_call_price'].notna())]
                    if len(blended_bonds) > 0:
                        print("\nAvailable blended bond issue_ids (first 10):")
                        print(blended_bonds['issue_id'].head(10).tolist())
                    else:
                        print("\nWarning: No blended bonds found in the dataset")
                return

        else:
            print(f"Error: Unknown mode '{sys.argv[1]}'")
            print("Available modes:")
            print("  curve        - Calculate price curve for any bond (by changing calculation date)")
            print("  blendedcurve - Specifically calculate price curve for blended bonds (by changing call date)")
            return
    else:

        print("Running batch calculation mode...")


        if 'make_whole' in df.columns:
            make_whole_count = df[df['make_whole'] == 'Y'].shape[0]
            print(f"Number of Make-Whole bonds: {make_whole_count}")
        else:
            print("Warning: No 'make_whole' field in the data")


        print("\nStarting to calculate Make-Whole prices (using Treasury yield curve)...")
        result_df = calculate_makewhole_batch_treasury(df, treasury_provider)


        original_cols = ['issue_id', 'coupon', 'principal_amt',
                         'maturity_s', 'calculation_date_s', 'freq_numeric', 'period_years']


        available_cols = [col for col in original_cols if col in df.columns]

        if 'make_whole' in df.columns:
            available_cols.append('make_whole')

        final_df = pd.merge(df[available_cols],
                            result_df[['issue_id', 'makewhole_price', 'price_per_100', 'make_whole_type', 'spread']],
                            on='issue_id', how='left')


        output_file = "makewhole_prices_treasury_method_fixed_with_spread.csv"
        final_df.to_csv(output_file, index=False)


        valid_prices = final_df['makewhole_price'].notna().sum()
        print(f"\nCalculation completed:")
        print(f"- Total number of bonds: {len(df)}")
        print(f"- Successfully calculated: {valid_prices} bonds")
        print(f"- Failed: {len(df) - valid_prices} bonds")

        if 'make_whole_type' in final_df.columns:
            blended_count = final_df[final_df['make_whole_type'] == 'Blended'].shape[0]
            pure_count = final_df[final_df['make_whole_type'] == 'Pure'].shape[0]
            print(f"- Blended: {blended_count}")
            print(f"- Pure Make-Whole Bonds: {pure_count}")


        print(f"\nMake-Whole prices for the first 10 bonds:")
        display_cols = ['issue_id', 'coupon', 'make_whole_type',
                        'principal_amt', 'makewhole_price', 'price_per_100', 'spread', 'freq_numeric', 'period_years']


        display_cols = [col for col in display_cols if col in final_df.columns]

        if display_cols:
            print(final_df[display_cols].head(10).to_string())


        if valid_prices > 0:

            if 'price_per_100' in final_df.columns:
                price_data = final_df['price_per_100'].dropna()
                if len(price_data) > 0:
                    print(f"\nPrice statistics (per 100):")
                    print(f"- Minimum: {price_data.min():.2f}")
                    print(f"- Maximum: {price_data.max():.2f}")
                    print(f"- Average: {price_data.mean():.2f}")
                    print(f"- Median: {price_data.median():.2f}")
                    print(f"- Standard deviation: {price_data.std():.2f}")


            if 'spread' in final_df.columns:
                spread_data = final_df['spread'].dropna()
                if len(spread_data) > 0:
                    print(f"\nSpread statistics (coupon rate - (Treasury rate + MW premium)):")
                    print(f"- Minimum: {spread_data.min():.4f} ({spread_data.min() * 100:.2f}%)")
                    print(f"- Maximum: {spread_data.max():.4f} ({spread_data.max() * 100:.2f}%)")
                    print(f"- Average: {spread_data.mean():.4f} ({spread_data.mean() * 100:.2f}%)")
                    print(f"- Median: {spread_data.median():.4f} ({spread_data.median() * 100:.2f}%)")
                    print(f"- Standard deviation: {spread_data.std():.4f} ({spread_data.std() * 100:.2f}%)")

        print(f"\nResults have been saved to: {output_file}")

       
        print("\nNote: You can use the following commands to calculate price curves for individual bonds:")
        print(" python MWBPS.py curve <issue_id> - Calculate price curve for any bond")
        print(" python MWBPS.py blendedcurve <issue_id> - Specifically calculate price curve for blended bonds")
        if 'issue_id' in df.columns:
            # Display a blended bond as an example
            blended_bonds = df[(df['make_whole'] == 'Y') & (df['next_call_price'].notna())]
            if len(blended_bonds) > 0:
                example_id = blended_bonds['issue_id'].iloc[0]
                print(f" For example: python MWBPS.py blendedcurve {example_id}")



if __name__ == "__main__":
    main_treasury()
