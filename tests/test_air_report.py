from src.app.report import render_report, fmt_signal


def test_air_signal_format_has_physical_units():
    assert fmt_signal("NO2_TRAFFIC", -3.2) == "-3.20 µg/m³"


def test_air_report_contains_research_and_reproduce_contract():
    run = {"id":"air1","domain":"air","case_id":"ulez-central-2019","created":"2026-01-01",
           "label":"Central ULEZ","event_date":"2019-04-08","post_months":3,
           "case":{"description":"test"},
           "verdict":{"status":"REAL","headline":"cleaner","statement":"s","lead_signal":"NO2_TRAFFIC"},
           "signals":{"NO2_TRAFFIC":{"point":-4.,"lo":-6.,"hi":-2.,"relative_pct":-10.,
                       "counterfactual_post_mean":40.,"treated_station_count":2,"n_donors":12,
                       "n_pre":100,"n_post":12,"pre_rmse":2.,"placebo_p":.05,"placebo_p_effect":.05,
                       "placebo_n":20,"placebo_cohort_size":2}},
           "donors":{},"stations":{"treated_usable":2,"control_usable":20},"data_summary":{},
           "research_comparison":[{"citation":"Paper","finding":"-10%","otherwise_pct":-10.,"otherwise_ugm3":-4.,"comparison":"inside"}],
           "limits":["limit"],"receipts":[],"method":{"plugin":"air"}}
    md = render_report(run)
    assert "Published-study comparison" in md
    assert "µg/m³" in md
    assert '"domain": "air"' in md
