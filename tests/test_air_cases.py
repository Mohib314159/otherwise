from src.app.air.cases import AIR_CASES


def test_registered_windows_and_geographies_are_not_generic_defaults():
    c19 = AIR_CASES["ulez-central-2019"]
    assert c19.analysis_start == "2018-03-08"
    assert c19.zone_mode == "arcgis" and c19.arcgis_layer == 4

    c21 = AIR_CASES["ulez-inner-2021"]
    assert c21.force_cant_tell is True
    assert c21.analysis_start == "2021-07-19"

    c23 = AIR_CASES["ulez-londonwide-2023"]
    assert c23.analysis_start == "2021-07-19"
    assert c23.zone_mode == "difference"
    assert c23.include_layer == 6 and c23.exclude_layer == 5
