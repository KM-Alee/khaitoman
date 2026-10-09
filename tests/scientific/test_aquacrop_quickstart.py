"""T5.4 gate 1: the published AquaCrop-OSPy quickstart runs unchanged."""

import pytest

pytestmark = pytest.mark.scientific


def test_quickstart_runs():
    # aquacrop/__init__.py skips its re-exports when "-m" is in sys.argv, which
    # `pytest -m scientific` triggers. Import from the defining submodules.
    from aquacrop.core import AquaCropModel
    from aquacrop.entities.crop import Crop
    from aquacrop.entities.inititalWaterContent import InitialWaterContent
    from aquacrop.entities.soil import Soil
    from aquacrop.utils.data import get_filepath
    from aquacrop.utils.prepare_weather import prepare_weather

    weather = prepare_weather(get_filepath("tunis_climate.txt"))
    model = AquaCropModel(
        sim_start_time="1979/10/01",
        sim_end_time="1985/05/30",
        weather_df=weather,
        soil=Soil(soil_type="SandyLoam"),
        crop=Crop("Wheat", planting_date="10/01"),
        initial_water_content=InitialWaterContent(value=["FC"]),
    )
    model.run_model(till_termination=True)
    results = model.get_simulation_results()
    assert len(results) > 0
    assert results.filter(like="Yield").select_dtypes("number").gt(0).any().any()
