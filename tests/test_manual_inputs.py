import pytest

from capex_tracker.data.manual_inputs import ManualInputError, load_guidance, load_segments

COMPANIES = {"MSFT": {}, "AMZN": {}}
SEG_HEADER = "company,period_end,segment,revenue_usd,source_accession,entered_date\n"
GUID_HEADER = "company,period,capex_guidance_low_usd,capex_guidance_high_usd,source,date_given\n"


def write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return p


def test_real_config_files_load():
    # The checked-in CSVs must always pass validation.
    load_segments()
    load_guidance()


def test_segments_valid_rows(tmp_path):
    p = write(tmp_path, "s.csv", SEG_HEADER +
              "AMZN,2024-03-31,AWS,25037000000,0001018724-24-000083,2026-11-18\n")
    df = load_segments(p, COMPANIES)
    assert df.loc[0, "revenue_usd"] == 25_037_000_000.0
    assert str(df.loc[0, "period_end"].date()) == "2024-03-31"


def test_segments_reject_missing_source_and_list_every_problem(tmp_path):
    p = write(tmp_path, "s.csv", SEG_HEADER +
              "AMZN,2024-03-31,AWS,25037000000,,2026-11-18\n"
              "XYZ,2024-13-01,AWS,abc,acc,2026-11-18\n")
    with pytest.raises(ManualInputError) as e:
        load_segments(p, COMPANIES)
    msg = str(e.value)
    for expected in ["row 2: source_accession is empty", "row 3: unknown company",
                     "row 3: period_end", "row 3: revenue_usd"]:
        assert expected in msg


def test_segments_reject_duplicates(tmp_path):
    row = "AMZN,2024-03-31,AWS,1,acc,2026-11-18\n"
    with pytest.raises(ManualInputError, match="duplicate"):
        load_segments(write(tmp_path, "s.csv", SEG_HEADER + row + row), COMPANIES)


def test_segments_missing_column(tmp_path):
    with pytest.raises(ManualInputError, match="missing columns"):
        load_segments(write(tmp_path, "s.csv", "company,period_end\n"), COMPANIES)


def test_guidance_valid_and_invalid(tmp_path):
    ok = write(tmp_path, "g.csv", GUID_HEADER + "MSFT,FY2026,80000000000,90000000000,https://example.com,2025-07-30\n")
    assert load_guidance(ok, COMPANIES).loc[0, "capex_guidance_high_usd"] == 90e9

    bad = write(tmp_path, "g2.csv", GUID_HEADER + "MSFT,2026,9,8,,2025-07-30\n")
    with pytest.raises(ManualInputError) as e:
        load_guidance(bad, COMPANIES)
    msg = str(e.value)
    assert "must look like FY2026" in msg and "source is empty" in msg and "low guidance is above" in msg
