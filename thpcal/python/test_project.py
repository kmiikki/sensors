import pytest
import numpy as np
from datetime import datetime
from project import extract_values, extract_datetime_from_end
from project import is_valid_mac, linear_regression
from project import compute_fitted_xy


# Test for extract_values
def test_extract_values():
    assert extract_values("%RHref") == ("%RHref", "")
    assert extract_values("RHref%") == ("RHref%", "")
    assert extract_values("Tref [°C]") == ("Tref", "°C")
    assert extract_values("Tref (°C)") == ("Tref", "°C")
    assert extract_values("Pref [hPa]") == ("Pref", "hPa")
    assert extract_values("Pref (hPa)") == ("Pref", "hPa")
    assert extract_values("invalid") is None


# Test for extract_datetime_from_end
def test_extract_datetime_from_end():
    # Valid datetime formats
    assert extract_datetime_from_end("file-2024-12-13-11:45:55") == datetime(2024, 12, 13, 11, 45, 55)
    assert extract_datetime_from_end("ABCDEF2024-12-13-114555") == datetime(2024, 12, 13, 11, 45, 55)
    assert extract_datetime_from_end("____2024-12-13 11:45:55") == datetime(2024, 12, 13, 11, 45, 55)
    assert extract_datetime_from_end(".....2024-12-13 114555") == datetime(2024, 12, 13, 11, 45, 55)
    assert extract_datetime_from_end("2024-12-13T11:45:55") == datetime(2024, 12, 13, 11, 45, 55)
    assert extract_datetime_from_end("F2024-12-13") == datetime(2024, 12, 13, 0, 0, 0)
    assert extract_datetime_from_end("srt++NJ20241213") == datetime(2024, 12, 13, 0, 0, 0)
    assert extract_datetime_from_end("...20241213-114555") == datetime(2024, 12, 13, 11, 45, 55)

    # Invalid strings that should return None
    assert extract_datetime_from_end("some text 2024-13-01") is None     # Invalid month
    assert extract_datetime_from_end("2024-12-32") is None               # Invalid day
    assert extract_datetime_from_end("2024-12-13 24:00:00") is None      # Invalid hour
    assert extract_datetime_from_end("no date here") is None             # No date or time
    assert extract_datetime_from_end("2024-12-13 notatend 11:45:55") is None  # datetime not at the end


# Test for is_valid_mac
def test_is_valid_mac():
    # Valid MAC addresses
    assert is_valid_mac("00:1A:2B:3C:4D:5E") == True   # Colons
    assert is_valid_mac("00-1A-2B-3C-4D-5E") == True   # Dashes
    assert is_valid_mac("001A2B3C4D5E") == True        # No separators
    assert is_valid_mac("00:1a:2b:3c:4d:5e") == True   # Mixed case
    assert is_valid_mac("00-1a-2b-3c-4d-5e") == True   # Mixed case with dashes

    # Invalid MAC addresses
    assert is_valid_mac("00:1A:2B:3C:4D") == False     # Too short
    assert is_valid_mac("00:1A:2B:3C:4D:5E:6F") == False # Too long
    assert is_valid_mac("00:1A:2B:3C:4D:5") == False   # Missing a digit
    assert is_valid_mac("00:1A:2B:3C:4D:5G") == False  # Invalid character
    assert is_valid_mac("00-1A-2B-3C-4D:5E") == False  # Mixed separators
    assert is_valid_mac("001:A2B3C4D5E") == False      # Invalid separator placement
    assert is_valid_mac("not a mac address") == False  # Random invalid string


# Test for linear_regression
def test_linear_regression():
    
    # Test slope 1
    sensor_values = np.array([1, 2, 3, 4, 5])
    ref_values = np.array([1, 2, 3, 4, 5])
    slope, intercept, r, r_squared, std_err, p_value = linear_regression(sensor_values, ref_values)
    assert pytest.approx(slope, 0.001) == 1
    assert pytest.approx(intercept, 0.001) == 0
    assert pytest.approx(r_squared, 0.001) == 1

    # Test slope 2
    sensor_values = np.array([1, 2, 3, 4, 5])
    ref_values = np.array([2, 4, 6, 8, 10])
    slope, intercept, r, r_squared, std_err, p_value = linear_regression(sensor_values, ref_values)
    assert pytest.approx(slope, 0.01) == 2
    assert pytest.approx(intercept, 0.001) == 0
    assert pytest.approx(r_squared, 0.001) == 1

    # Test slope 3
    sensor_values = np.array([1, 2, 3, 4, 5])
    ref_values = np.array([3, 6, 9, 12, 15])
    slope, intercept, r, r_squared, std_err, p_value = linear_regression(sensor_values, ref_values)
    assert pytest.approx(slope, 0.01) == 3
    assert pytest.approx(intercept, 0.001) == 0
    assert pytest.approx(r_squared, 0.001) == 1


# Test for compute_fitted_xy
def test_compute_fitted_xy():
    slope = 2
    intercept = 1
    x_min, x_max = 0, 10
    steps = 5
    x_fit, y_fit = compute_fitted_xy(slope, intercept, (x_min, x_max), steps)

    expected_x_fit = np.linspace(x_min, x_max, steps)
    expected_y_fit = slope * expected_x_fit + intercept

    assert np.allclose(x_fit, expected_x_fit)
    assert np.allclose(y_fit, expected_y_fit)


if __name__ == "__main__":
    pytest.main()
