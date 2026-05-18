"""
test_input_logic.py
====================
Unit tests for data input logic in the Forecast Deck Builder.

Tests cover:
1. CSV file input handling
2. Excel files with no DATA sheet
3. Strange/unusual month formats (using production _clean_month_column)
"""

import pytest
import pandas as pd
import tempfile
import os
from pathlib import Path

# Import modules under test
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from acc_deck_pkg.data_io import (
    _detect_file_type,
    _load_file,
    _lower_trim_cols,
    _clean_month_column,
    load_data,
)


# ============================================================================
# Fixtures - Test Data Generators
# ============================================================================

@pytest.fixture
def sample_actuals_data():
    """Generate sample actuals data"""
    return pd.DataFrame({
        'project': ['Industry A', 'Industry A', 'Industry B', 'Industry B'],
        'highlevelrollup': ['Category 1', 'Category 2', 'Category 1', 'Category 2'],
        'month': ['2025-01-01', '2025-01-01', '2025-01-01', '2025-01-01'],
        'units_actual': [1000, 2000, 1500, 2500],
        'dollars_actual': [10000, 20000, 15000, 25000],
    })


@pytest.fixture
def sample_forecast_data():
    """Generate sample forecast data"""
    return pd.DataFrame({
        'project': ['Industry A', 'Industry A', 'Industry B', 'Industry B'],
        'highlevelrollup': ['Category 1', 'Category 2', 'Category 1', 'Category 2'],
        'month': ['2025-01-01', '2025-01-01', '2025-01-01', '2025-01-01'],
        'units_final': [950, 1900, 1400, 2400],
        'dollars_final': [9500, 19000, 14000, 24000],
    })


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


# ============================================================================
# Test 1: CSV File Input
# ============================================================================

class TestCSVInput:
    """Tests for CSV file handling"""

    def test_detect_csv_file_type(self):
        """Test that CSV files are correctly identified"""
        assert _detect_file_type("data.csv") == "csv"
        assert _detect_file_type("path/to/file.CSV") == "csv"
        assert _detect_file_type("my_data.csv") == "csv"

    def test_detect_excel_file_type(self):
        """Test that Excel files are correctly identified"""
        assert _detect_file_type("data.xlsx") == "excel"
        assert _detect_file_type("data.xls") == "excel"
        assert _detect_file_type("path/to/file.XLSX") == "excel"

    def test_detect_unknown_file_type(self):
        """Test that unknown file types return 'unknown'"""
        assert _detect_file_type("data.txt") == "unknown"
        assert _detect_file_type("data.json") == "unknown"
        assert _detect_file_type("noextension") == "unknown"

    def test_load_csv_file(self, sample_actuals_data, temp_dir):
        """Test loading a CSV file"""
        csv_path = os.path.join(temp_dir, "test_actuals.csv")
        sample_actuals_data.to_csv(csv_path, index=False)

        loaded_df = _load_file(csv_path)

        assert len(loaded_df) == 4
        assert 'project' in loaded_df.columns
        assert 'units_actual' in loaded_df.columns
        assert loaded_df['units_actual'].sum() == 7000

    def test_load_csv_with_special_characters(self, temp_dir):
        """Test loading CSV with special characters in data"""
        data = pd.DataFrame({
            'project': ['Industry "A"', "Industry's B", 'Category, C'],
            'value': [100, 200, 300],
        })
        csv_path = os.path.join(temp_dir, "special_chars.csv")
        data.to_csv(csv_path, index=False)

        loaded_df = _load_file(csv_path)
        assert len(loaded_df) == 3

    def test_full_pipeline_with_csv(self, sample_actuals_data, sample_forecast_data, temp_dir):
        """Test full data loading pipeline with CSV files"""
        actuals_path = os.path.join(temp_dir, "actuals.csv")
        forecast_path = os.path.join(temp_dir, "forecast.csv")

        sample_actuals_data.to_csv(actuals_path, index=False)
        sample_forecast_data.to_csv(forecast_path, index=False)

        cfg = {
            "paths": {
                "actual": actuals_path,
                "forecast": forecast_path,
            },
            "column_map": {
                "actual": {
                    "level1": "project",
                    "level2": "highlevelrollup",
                    "units": "units_actual",
                    "dollars": "dollars_actual",
                },
                "forecast": {
                    "level1": "project",
                    "level2": "highlevelrollup",
                    "units": "units_final",
                    "dollars": "dollars_final",
                },
                "time": {"month": "month"},
            },
        }

        result = load_data(cfg)

        assert len(result) > 0
        assert 'level1' in result.columns
        assert 'units_latest' in result.columns
        assert 'units_prevwave' in result.columns


# ============================================================================
# Test 2: Excel with No DATA Sheet
# ============================================================================

class TestExcelNoDataSheet:
    """Tests for Excel files without a DATA sheet"""

    def test_load_excel_single_sheet(self, sample_actuals_data, temp_dir):
        """Test loading Excel file with only one sheet (should work regardless of name)"""
        xlsx_path = os.path.join(temp_dir, "single_sheet.xlsx")
        sample_actuals_data.to_excel(xlsx_path, sheet_name="MyCustomSheet", index=False)

        # Should load successfully - single sheet Excel defaults to that sheet
        loaded_df = _load_file(xlsx_path)

        assert len(loaded_df) == 4
        assert 'project' in loaded_df.columns

    def test_load_excel_multi_sheet_no_data(self, sample_actuals_data, temp_dir):
        """Test loading Excel file with multiple sheets but no DATA sheet"""
        xlsx_path = os.path.join(temp_dir, "multi_sheet_no_data.xlsx")

        with pd.ExcelWriter(xlsx_path, engine='openpyxl') as writer:
            sample_actuals_data.to_excel(writer, sheet_name="Sheet1", index=False)
            pd.DataFrame({'info': ['metadata']}).to_excel(writer, sheet_name="Info", index=False)

        # Without specifying sheet_name, should load first sheet
        loaded_df = _load_file(xlsx_path)
        assert len(loaded_df) == 4

    def test_load_excel_with_specified_sheet(self, sample_actuals_data, temp_dir):
        """Test loading Excel with a specified sheet name"""
        xlsx_path = os.path.join(temp_dir, "specified_sheet.xlsx")

        with pd.ExcelWriter(xlsx_path, engine='openpyxl') as writer:
            sample_actuals_data.to_excel(writer, sheet_name="RawData", index=False)
            pd.DataFrame({'info': ['metadata']}).to_excel(writer, sheet_name="Info", index=False)

        loaded_df = _load_file(xlsx_path, sheet_name="RawData")
        assert len(loaded_df) == 4
        assert 'project' in loaded_df.columns

    def test_load_excel_missing_specified_sheet(self, sample_actuals_data, temp_dir):
        """Test that loading a non-existent sheet raises an error"""
        xlsx_path = os.path.join(temp_dir, "missing_sheet.xlsx")
        sample_actuals_data.to_excel(xlsx_path, sheet_name="Actual", index=False)

        with pytest.raises(ValueError):
            _load_file(xlsx_path, sheet_name="NonExistentSheet")

    def test_pipeline_excel_no_data_sheet_uses_config(self, sample_actuals_data, sample_forecast_data, temp_dir):
        """Test pipeline handles Excel without DATA sheet when sheet is configured"""
        actuals_path = os.path.join(temp_dir, "actuals.xlsx")
        forecast_path = os.path.join(temp_dir, "forecast.xlsx")

        # Create Excel files with custom sheet names
        sample_actuals_data.to_excel(actuals_path, sheet_name="ActualsData", index=False)

        with pd.ExcelWriter(forecast_path, engine='openpyxl') as writer:
            sample_forecast_data.to_excel(writer, sheet_name="ForecastData", index=False)
            pd.DataFrame({'note': ['metadata']}).to_excel(writer, sheet_name="Notes", index=False)

        cfg = {
            "paths": {
                "actual": actuals_path,
                "forecast": forecast_path,
            },
            "sheet_name_forecast": "ForecastData",
            "column_map": {
                "actual": {
                    "level1": "project",
                    "level2": "highlevelrollup",
                    "units": "units_actual",
                    "dollars": "dollars_actual",
                },
                "forecast": {
                    "level1": "project",
                    "level2": "highlevelrollup",
                    "units": "units_final",
                    "dollars": "dollars_final",
                },
                "time": {"month": "month"},
            },
        }

        result = load_data(cfg)
        assert len(result) > 0


# ============================================================================
# Test 3: Strange Month Formats - Using Production _clean_month_column
# ============================================================================

class TestStrangeMonthFormats:
    """Tests for unusual date/month format handling using production code"""

    def test_iso_date_format(self):
        """Test ISO format dates (YYYY-MM-DD) via production function"""
        series = pd.Series(['2025-01-15', '2025-02-15'])
        result = _clean_month_column(series, source_name="test")

        assert result.notna().all()
        assert result.iloc[0].year == 2025
        assert result.iloc[0].month == 1
        assert result.iloc[0].day == 15

    def test_us_date_format(self):
        """Test US format dates (MM/DD/YYYY) via production function"""
        series = pd.Series(['01/15/2025', '02/15/2025'])
        result = _clean_month_column(series, source_name="test")

        assert result.notna().all()
        assert result.iloc[0].month == 1
        assert result.iloc[0].day == 15

    def test_uk_date_format(self):
        """Test UK format dates (DD/MM/YYYY) via production function"""
        series = pd.Series(['15/01/2025', '15/02/2025'])
        result = _clean_month_column(series, source_name="test")

        assert result.notna().all()
        assert result.iloc[0].day == 15
        assert result.iloc[0].month == 1

    def test_excel_serial_date_format(self):
        """Test Excel serial date numbers via production function"""
        # Excel serial: 45672 = 2025-01-29 (days since 1899-12-30)
        series = pd.Series([45672, 45703])
        result = _clean_month_column(series, source_name="test")

        assert result.notna().all()
        assert result.iloc[0].year == 2025

    def test_text_month_format(self):
        """Test text month format (Jan 15, 2025) via production function"""
        series = pd.Series(['Jan 15, 2025', 'Feb 15, 2025'])
        result = _clean_month_column(series, source_name="test")

        assert result.notna().all()
        assert result.iloc[0].month == 1

    def test_full_month_name_format(self):
        """Test full month name format (January 15, 2025) via production function"""
        series = pd.Series(['January 15, 2025', 'February 15, 2025'])
        result = _clean_month_column(series, source_name="test")

        assert result.notna().all()
        assert result.iloc[0].month == 1

    def test_european_format_with_dots(self):
        """Test European format with dots (15.01.2025) via production function"""
        series = pd.Series(['15.01.2025', '15.02.2025'])
        result = _clean_month_column(series, source_name="test")

        assert result.notna().all()
        assert result.iloc[0].day == 15
        assert result.iloc[0].month == 1

    def test_short_year_format(self):
        """Test short year format (01/15/25) via production function"""
        series = pd.Series(['01/15/25', '02/15/25'])
        result = _clean_month_column(series, source_name="test")

        assert result.notna().all()
        # Should parse to 2025
        assert result.iloc[0].year == 2025

    def test_already_datetime(self):
        """Test that already-parsed datetime objects pass through"""
        series = pd.Series([pd.Timestamp('2025-01-15'), pd.Timestamp('2025-02-15')])
        result = _clean_month_column(series, source_name="test")

        assert result.notna().all()
        assert result.iloc[0].year == 2025

    def test_mixed_valid_formats(self):
        """Test that mixed but valid date formats all parse correctly"""
        series = pd.Series([
            '2025-01-15',      # ISO
            '01/15/2025',      # US
            'Jan 15, 2025',    # Text month
        ])
        result = _clean_month_column(series, source_name="test")

        assert result.notna().all()
        # All should be January 15, 2025
        for dt in result:
            assert dt.month == 1
            assert dt.day == 15
            assert dt.year == 2025

    def test_garbage_date_raises_error_when_all_fail(self):
        """Test that all unparseable dates raises ValueError"""
        series = pd.Series(['garbage', 'nonsense', 'invalid'])

        with pytest.raises(ValueError) as exc_info:
            _clean_month_column(series, source_name="test")

        assert "Could not parse ANY dates" in str(exc_info.value)

    def test_high_failure_rate_raises_error(self):
        """Test that >10% failure rate raises ValueError"""
        # 5 valid, 6 invalid = 54% failure rate
        series = pd.Series([
            '2025-01-01', '2025-01-02', '2025-01-03', '2025-01-04', '2025-01-05',
            'bad1', 'bad2', 'bad3', 'bad4', 'bad5', 'bad6'
        ])

        with pytest.raises(ValueError) as exc_info:
            _clean_month_column(series, source_name="test")

        assert "could not be parsed" in str(exc_info.value)

    def test_low_failure_rate_warns_but_continues(self):
        """Test that <=10% failure rate warns but continues"""
        # 19 valid, 1 invalid = 5% failure rate
        valid_dates = [f'2025-01-{i:02d}' for i in range(1, 20)]
        series = pd.Series(valid_dates + ['garbage'])

        result = _clean_month_column(series, source_name="test")

        # Should have 19 valid dates and 1 NaT
        assert result.notna().sum() == 19
        assert pd.isna(result.iloc[-1])

    def test_empty_strings_become_nat(self):
        """Test that empty strings become NaT"""
        series = pd.Series(['2025-01-15', '', '  ', '2025-02-15'])
        result = _clean_month_column(series, source_name="test")

        assert result.iloc[0].year == 2025
        assert pd.isna(result.iloc[1])
        assert pd.isna(result.iloc[2])
        assert result.iloc[3].year == 2025

    def test_none_values_become_nat(self):
        """Test that None values become NaT"""
        series = pd.Series(['2025-01-15', None, '2025-02-15'])
        result = _clean_month_column(series, source_name="test")

        assert result.iloc[0].year == 2025
        assert pd.isna(result.iloc[1])
        assert result.iloc[2].year == 2025


class TestFullPipelineWithDateFormats:
    """Integration tests for full pipeline with various date formats"""

    def test_pipeline_with_european_dates(self, temp_dir):
        """Test full pipeline with European date format (DD.MM.YYYY)

        Note: Pipeline merges on quarterly keys (year, quarter, level1, level2).
        Rows within the same quarter and category are aggregated.
        """
        # Use dates in different quarters to test quarterly merge
        # Q1: Jan 15, Q2: Apr 15 - different quarters = 2 output rows
        actuals = pd.DataFrame({
            'project': ['A', 'A'],
            'highlevelrollup': ['Cat1', 'Cat1'],
            'month': ['15.01.2025', '15.04.2025'],  # Q1 and Q2
            'units_actual': [100, 200],
            'dollars_actual': [1000, 2000],
        })
        forecast = pd.DataFrame({
            'project': ['A', 'A'],
            'highlevelrollup': ['Cat1', 'Cat1'],
            'month': ['15.01.2025', '15.04.2025'],  # Q1 and Q2
            'units_final': [90, 180],
            'dollars_final': [900, 1800],
        })

        actuals_path = os.path.join(temp_dir, "actuals.csv")
        forecast_path = os.path.join(temp_dir, "forecast.csv")
        actuals.to_csv(actuals_path, index=False)
        forecast.to_csv(forecast_path, index=False)

        cfg = {
            "paths": {"actual": actuals_path, "forecast": forecast_path},
            "column_map": {
                "actual": {"level1": "project", "level2": "highlevelrollup",
                           "units": "units_actual", "dollars": "dollars_actual"},
                "forecast": {"level1": "project", "level2": "highlevelrollup",
                             "units": "units_final", "dollars": "dollars_final"},
                "time": {"month": "month"},
            },
        }

        result = load_data(cfg)
        # 2 rows: one for Q1, one for Q2 (same level1/level2)
        assert len(result) == 2
        # Verify European date parsing worked (first row is Q1)
        assert result['quarter'].iloc[0] == 1

    def test_pipeline_with_excel_serial_dates(self, temp_dir):
        """Test full pipeline with Excel serial date numbers

        Note: Pipeline merges on quarterly keys (year, quarter, level1, level2).
        Rows within the same quarter and category are aggregated.
        """
        # Use dates in different quarters to test quarterly merge
        # 45672 = 2025-01-29 (Q1), 45764 = 2025-05-01 (Q2)
        actuals = pd.DataFrame({
            'project': ['A', 'A'],
            'highlevelrollup': ['Cat1', 'Cat1'],
            'month': [45672, 45764],  # Q1 and Q2
            'units_actual': [100, 200],
            'dollars_actual': [1000, 2000],
        })
        forecast = pd.DataFrame({
            'project': ['A', 'A'],
            'highlevelrollup': ['Cat1', 'Cat1'],
            'month': [45672, 45764],  # Q1 and Q2
            'units_final': [90, 180],
            'dollars_final': [900, 1800],
        })

        actuals_path = os.path.join(temp_dir, "actuals.xlsx")
        forecast_path = os.path.join(temp_dir, "forecast.xlsx")
        actuals.to_excel(actuals_path, index=False)
        forecast.to_excel(forecast_path, index=False)

        cfg = {
            "paths": {"actual": actuals_path, "forecast": forecast_path},
            "column_map": {
                "actual": {"level1": "project", "level2": "highlevelrollup",
                           "units": "units_actual", "dollars": "dollars_actual"},
                "forecast": {"level1": "project", "level2": "highlevelrollup",
                             "units": "units_final", "dollars": "dollars_final"},
                "time": {"month": "month"},
            },
        }

        result = load_data(cfg)
        # 2 rows: one for Q1, one for Q2 (same level1/level2)
        assert len(result) == 2
        assert result['month'].iloc[0].year == 2025


# ============================================================================
# Test Helper Functions
# ============================================================================

class TestHelperFunctions:
    """Tests for utility/helper functions"""

    def test_lower_trim_cols(self):
        """Test column name normalization"""
        df = pd.DataFrame({
            'Project ': [1],
            ' UNITS': [2],
            'Mixed Case': [3],
        })

        result = _lower_trim_cols(df)

        assert 'project' in result.columns
        assert 'units' in result.columns
        assert 'mixed case' in result.columns

    def test_file_not_found(self):
        """Test that FileNotFoundError is raised for missing files"""
        with pytest.raises(FileNotFoundError):
            _load_file("/nonexistent/path/to/file.csv")


# ============================================================================
# Run tests if executed directly
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
