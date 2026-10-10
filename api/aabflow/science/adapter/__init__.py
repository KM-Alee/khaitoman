"""CropSimulatorAdapter: one CropExperiment -> one audited AquaCrop run (T5.2, T5.3).

Rules enforced here:

* fresh Crop/Soil/InitialWaterContent/IrrigationManagement objects per run;
* the schedule is a typed ``Date``/``Depth`` frame; several events on one
  local day are aggregated; events outside [planting, sim_end] are rejected;
* ``MaxIrr`` / ``MaxIrrSeason`` are set explicitly from the crop profile and a
  schedule above them is rejected (never silently clipped);
* ``AppEff`` is passed once, as percent, via ``units``; the ledger records gross
  depth, AquaCrop applies the efficiency inside infiltration;
* the installed constructor is asserted to have taken the schedule;
* every day, applied ``IrrDay`` equals the scheduled gross depth, else the
  experiment fails (clipping, out-of-season, unsupported keys);
* outputs come from the documented getters; raw frames are kept with their
  original column names; trailing preallocated rows past termination are
  masked; the season must have finished with a harvest row;
* yield tonne/ha -> kg/ha exactly once, carrying ``yield_basis``.
"""

from __future__ import annotations

import importlib.metadata
import warnings
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from aabflow.domain import units
from aabflow.domain.schemas import CropExperiment, CropProfile, SoilProfile
from aabflow.science import crop_profiles, soils

ADAPTER_VERSION = "aabflow-aquacrop-adapter-1.0.0"
FIELD_MAPPING_VERSION = "aquacrop-3.1.0-output-map-v1"
ENGINE_NAME = "aquacrop-ospy"
AUDIT_TOLERANCE_MM = 1e-6
N_COMPARTMENTS = 12

# Raw columns verified in the installed 3.1.0 package (T5.3).
RESULT_COLUMNS = [
    "Season",
    "crop Type",
    "Harvest Date (YYYY/MM/DD)",
    "Harvest Date (Step)",
    "Dry yield (tonne/ha)",
    "Fresh yield (tonne/ha)",
    "Yield potential (tonne/ha)",
    "Seasonal irrigation (mm)",
]
FLUX_REQUIRED = [
    "time_step_counter",
    "dap",
    "Wr",
    "IrrDay",
    "Infl",
    "Runoff",
    "DeepPerc",
    "Es",
    "Tr",
]
GROWTH_REQUIRED = ["time_step_counter", "dap", "gdd_cum", "z_root", "canopy_cover", "biomass"]


def engine_version() -> str:
    return importlib.metadata.version("aquacrop")


class CropAdapterError(RuntimeError):
    """The experiment is invalid or failed its audit; no crop metrics may be used."""


class IrrigationAuditError(CropAdapterError):
    """Applied irrigation differs from the schedule (clipping, off-season, ignored keys)."""


class PostTerminationError(IrrigationAuditError):
    """Irrigation was scheduled after the crop terminated (``last_day`` = last simulated day)."""

    def __init__(self, message: str, last_day: date):
        super().__init__(message)
        self.last_day = last_day


def audit_daily_irrigation(
    dates: pd.DatetimeIndex,
    applied_mm: np.ndarray,
    scheduled_mm: np.ndarray,
    unapplied_after_mm: float = 0.0,
) -> None:
    """Every day, package-reported gross irrigation must equal the scheduled gross depth (T5.3)."""
    applied = np.asarray(applied_mm, dtype="float64")
    expected = np.asarray(scheduled_mm, dtype="float64")
    if applied.shape != expected.shape:
        raise IrrigationAuditError(
            f"audit arrays differ in length {applied.shape} vs {expected.shape}"
        )
    diff = np.abs(applied - expected)
    if (diff > AUDIT_TOLERANCE_MM).any():
        bad = np.nonzero(diff > AUDIT_TOLERANCE_MM)[0][:5]
        detail = [
            f"{dates[i].date()} scheduled={expected[i]:.3f} applied={applied[i]:.3f}" for i in bad
        ]
        raise IrrigationAuditError(
            f"daily irrigation audit failed (clipped/out-of-season): {detail}"
        )
    if unapplied_after_mm > AUDIT_TOLERANCE_MM:
        raise PostTerminationError(
            f"{unapplied_after_mm:.3f} mm scheduled after crop termination {dates[-1].date()} was not applied",
            dates[-1].date(),
        )


@dataclass
class AdapterResult:
    planting_date: date
    harvest_date: date | None
    has_finished: bool
    yield_t_ha_raw: float
    yield_kg_ha: float
    seasonal_irrigation_mm: float
    raw: dict[str, pd.DataFrame]
    trajectory: pd.DataFrame
    warnings: list[str] = field(default_factory=list)


def schedule_frame(exp: CropExperiment) -> pd.DataFrame:
    """Aggregate events per local day into the typed frame AquaCrop expects."""
    if not exp.schedule:
        return pd.DataFrame(
            {"Date": pd.Series([], dtype="datetime64[ns]"), "Depth": pd.Series([], dtype="float64")}
        )
    agg: dict[date, float] = {}
    for ev in exp.schedule:
        agg[ev.date] = agg.get(ev.date, 0.0) + units.nonnegative(ev.gross_depth_mm, "depth_mm")
    days = sorted(d for d, v in agg.items() if v > 0)
    return pd.DataFrame(
        {
            "Date": pd.to_datetime(pd.Series(days)).astype("datetime64[ns]"),
            "Depth": pd.Series([agg[d] for d in days], dtype="float64"),
        }
    )


class CropSimulatorAdapter:
    def __init__(
        self, crop_profile: CropProfile | None = None, soil_profile: SoilProfile | None = None
    ):
        self._crop = crop_profile
        self._soil = soil_profile

    def resolve(self, exp: CropExperiment) -> tuple[CropProfile, SoilProfile]:
        cp = self._crop or crop_profiles.profile(exp.crop_profile_id)
        sp = self._soil or soils.soil(exp.soil_profile_id)
        if cp.crop_profile_id != exp.crop_profile_id or sp.soil_profile_id != exp.soil_profile_id:
            raise CropAdapterError("resolved profiles do not match the experiment ids")
        return cp, soils.validate_soil(sp)

    def evaluate(self, exp: CropExperiment, weather: pd.DataFrame) -> AdapterResult:
        # Import from defining submodules: aquacrop/__init__ drops exports under `-m`.
        from aquacrop.core import AquaCropModel
        from aquacrop.entities.crop import Crop
        from aquacrop.entities.inititalWaterContent import InitialWaterContent
        from aquacrop.entities.irrigationManagement import IrrigationManagement
        from aquacrop.entities.soil import Soil

        cp, sp = self.resolve(exp)
        if exp.sim_end <= exp.sim_start:
            raise CropAdapterError("sim_end must be after sim_start")
        planting = crop_profiles.planting_in_window(cp, exp.sim_start)
        if planting > exp.sim_end:
            raise CropAdapterError(f"planting {planting} falls after sim_end {exp.sim_end}")

        sched = schedule_frame(exp)
        # Physical admissibility before the engine sees anything.
        assert list(sched.columns) == ["Date", "Depth"]
        if not sched["Date"].is_unique:
            raise CropAdapterError("schedule dates must be unique after aggregation")
        if (sched["Depth"] < 0).any():
            raise CropAdapterError("negative irrigation depth")
        if len(sched) and sched["Depth"].max() > cp.max_daily_irrigation_mm + 1e-9:
            raise CropAdapterError(
                f"daily depth {sched['Depth'].max():.3f} mm exceeds the declared field "
                f"application limit {cp.max_daily_irrigation_mm} mm (would be clipped)"
            )
        if sched["Depth"].sum() > cp.max_season_irrigation_mm + 1e-9:
            raise CropAdapterError(
                f"seasonal depth {sched['Depth'].sum():.3f} mm exceeds {cp.max_season_irrigation_mm}"
            )
        if len(sched):
            first, last = sched["Date"].min().date(), sched["Date"].max().date()
            if first < planting or last > exp.sim_end:
                raise CropAdapterError(
                    f"irrigation event outside the active crop interval "
                    f"[{planting}, {exp.sim_end}]: first={first} last={last} "
                    "(pre-plant/off-season field irrigation is unsupported in v2)"
                )

        app_eff_pct = units.application_efficiency_to_aquacrop_percent(exp.application_efficiency)
        management = IrrigationManagement(
            irrigation_method=3,
            Schedule=sched.copy(),
            AppEff=app_eff_pct,
            MaxIrr=float(cp.max_daily_irrigation_mm),
            MaxIrrSeason=float(cp.max_season_irrigation_mm),
        )
        if not (
            isinstance(management.Schedule, pd.DataFrame) and management.Schedule.equals(sched)
        ):
            raise CropAdapterError("installed IrrigationManagement did not take the Schedule key")
        if (
            management.AppEff != app_eff_pct
            or management.MaxIrr != cp.max_daily_irrigation_mm
            or management.MaxIrrSeason != cp.max_season_irrigation_mm
        ):
            raise CropAdapterError("installed IrrigationManagement ignored AppEff/MaxIrr keys")

        w = weather.copy()
        w["Date"] = pd.to_datetime(w["Date"]).astype("datetime64[ns]")
        win = w[
            (w["Date"] >= pd.Timestamp(exp.sim_start)) & (w["Date"] <= pd.Timestamp(exp.sim_end))
        ]
        n_days = (exp.sim_end - exp.sim_start).days + 1
        if len(win) != n_days:
            raise CropAdapterError(f"weather covers {len(win)} of {n_days} simulation days")
        wc_type, wc_value = soils.parse_initial_water(sp.initial_water)
        crop_kwargs = dict(cp.parameter_overrides)
        caught: list[str] = []
        with warnings.catch_warnings(record=True) as rec:
            warnings.simplefilter("always")
            model = AquaCropModel(
                sim_start_time=exp.sim_start.strftime("%Y/%m/%d"),
                sim_end_time=exp.sim_end.strftime("%Y/%m/%d"),
                # Column order matters: the engine indexes weather[:, 4] as Date.
                weather_df=win[
                    ["MinTemp", "MaxTemp", "Precipitation", "ReferenceET", "Date"]
                ].reset_index(drop=True),
                soil=Soil(soil_type=sp.engine_soil_type),
                crop=Crop(
                    cp.engine_crop_name, planting_date=planting.strftime("%m/%d"), **crop_kwargs
                ),
                initial_water_content=InitialWaterContent(wc_type=wc_type, value=list(wc_value)),
                irrigation_management=management,
            )
            model.run_model(till_termination=True)
            caught = sorted({f"{r.category.__name__}: {r.message}" for r in rec})

        results = model.get_simulation_results()
        flux = model.get_water_flux()
        storage = model.get_water_storage()
        growth = model.get_crop_growth()
        raw = {
            "simulation_results": results.copy(),
            "water_flux": flux.copy(),
            "water_storage": storage.copy(),
            "crop_growth": growth.copy(),
        }
        return self._normalize(exp, cp, planting, raw, sched, caught, model)

    # ------------------------------------------------------------------ normalization

    def _normalize(self, exp, cp, planting, raw, sched, caught, model) -> AdapterResult:
        results, flux, storage, growth = (
            raw["simulation_results"],
            raw["water_flux"],
            raw["water_storage"],
            raw["crop_growth"],
        )
        missing = [c for c in RESULT_COLUMNS if c not in results.columns]
        missing += [c for c in FLUX_REQUIRED if c not in flux.columns]
        missing += [c for c in GROWTH_REQUIRED if c not in growth.columns]
        if missing:
            raise CropAdapterError(f"installed AquaCrop output lacks verified columns {missing}")
        if len(results) != 1:
            raise CropAdapterError(
                f"season did not finish with exactly one harvest row (rows={len(results)}); "
                "a simulation stopped before maturity is not a yield experiment"
            )
        row = results.iloc[0]
        harvest_ts = pd.Timestamp(row["Harvest Date (YYYY/MM/DD)"])
        if pd.isna(harvest_ts):
            raise CropAdapterError("no harvest date reported")
        harvest = harvest_ts.date()
        if not (planting < harvest <= exp.sim_end):
            raise CropAdapterError(f"harvest {harvest} outside ({planting}, {exp.sim_end}]")

        time_span = pd.DatetimeIndex(model._clock_struct.time_span)
        n = len(time_span)
        # Valid rows: the engine writes time_step_counter == row index; preallocated
        # trailing rows after termination stay zero and are masked.
        tsc = flux["time_step_counter"].to_numpy()
        idx = np.arange(len(tsc))
        valid = np.zeros(len(tsc), dtype=bool)
        valid[0] = True
        valid[1:] = tsc[1:] == idx[1:]
        last_valid = int(np.max(np.nonzero(valid)[0]))
        if not valid[: last_valid + 1].all():
            raise CropAdapterError("engine output rows are not contiguous up to termination")
        if pd.Timestamp(harvest) > time_span[min(last_valid + 1, n - 1)]:
            raise CropAdapterError("harvest date beyond the last simulated row")
        dates = time_span[: last_valid + 1]

        # Daily audit: package-reported gross irrigation equals the schedule.
        sched_series = pd.Series(0.0, index=time_span)
        for d, depth in zip(sched["Date"], sched["Depth"], strict=True):
            sched_series[pd.Timestamp(d)] += float(depth)
        applied = flux["IrrDay"].to_numpy(dtype="float64")[: last_valid + 1]
        expected = sched_series.to_numpy()[: last_valid + 1]
        unapplied = float(sched_series.to_numpy()[last_valid + 1 :].sum())
        audit_daily_irrigation(dates, applied, expected, unapplied)
        seasonal_irr = float(row["Seasonal irrigation (mm)"])
        if abs(seasonal_irr - float(sched["Depth"].sum())) > 1e-6:
            raise CropAdapterError(
                f"seasonal irrigation {seasonal_irr} != scheduled {sched['Depth'].sum()}"
            )

        dry_t_ha = float(row["Dry yield (tonne/ha)"])
        if not np.isfinite(dry_t_ha) or dry_t_ha < 0:
            raise CropAdapterError(f"nonfinite/negative yield {dry_t_ha}")
        yield_kg_ha = units.t_ha_to_kg_ha(dry_t_ha)  # the single tonne->kg conversion

        g = growth.iloc[: last_valid + 1]
        f = flux.iloc[: last_valid + 1]
        s = storage.iloc[: last_valid + 1]
        th_cols = [f"th{i}" for i in range(1, N_COMPARTMENTS + 1) if f"th{i}" in s.columns]
        # Compartment water content is m3/m3; storage uses the engine's actual
        # compartment thicknesses (it extends the profile to cover Zmax).
        dz = model.soil.profile["dz"].to_numpy(dtype="float64")[: len(th_cols)]
        if len(dz) != len(th_cols):
            raise CropAdapterError("compartment thicknesses do not match storage columns")
        profile_mm = s[th_cols].to_numpy(dtype="float64") @ dz * 1000.0
        wmask = (model.weather_df["Date"] >= dates[0]) & (model.weather_df["Date"] <= dates[-1])
        wv = model.weather_df.loc[wmask]
        traj = pd.DataFrame(
            {
                "date": dates.strftime("%Y-%m-%d"),
                "dap": g["dap"].to_numpy(dtype="int64"),
                "growing_season": s["growing_season"].to_numpy(dtype="float64") > 0,
                "gross_irrigation_mm": applied,
                "infiltrated_mm": f["Infl"].to_numpy(dtype="float64"),
                "precipitation_mm": wv["Precipitation"].to_numpy(dtype="float64"),
                "reference_et_mm": wv["ReferenceET"].to_numpy(dtype="float64"),
                "canopy_fraction": g["canopy_cover"].to_numpy(dtype="float64"),
                # AquaCrop-OSPy biomass is g/m2; x10 -> kg/ha (verified: B*HIadj/100 = DryYield t/ha)
                "biomass_kg_ha": g["biomass"].to_numpy(dtype="float64") * 10.0,
                "gdd_cum": g["gdd_cum"].to_numpy(dtype="float64"),
                "root_depth_m": g["z_root"].to_numpy(dtype="float64"),
                "soil_profile_water_mm": profile_mm,
                "root_zone_water_mm": f["Wr"].to_numpy(dtype="float64"),
                "evaporation_mm": f["Es"].to_numpy(dtype="float64"),
                "transpiration_mm": f["Tr"].to_numpy(dtype="float64"),
                "et_mm": f["Es"].to_numpy(dtype="float64") + f["Tr"].to_numpy(dtype="float64"),
                "runoff_mm": f["Runoff"].to_numpy(dtype="float64"),
                "deep_percolation_mm": f["DeepPerc"].to_numpy(dtype="float64"),
            }
        )
        if not np.isfinite(traj.select_dtypes("number").to_numpy()).all():
            raise CropAdapterError("nonfinite values in daily trajectory")
        # Yield-basis identity check against the crop-growth table (gate 7).
        if "DryYield" in g.columns and "harvest_index_adj" in g.columns:
            final_dry = float(g["DryYield"].iloc[-1])
            if abs(final_dry - dry_t_ha) > 1e-6 * max(1.0, dry_t_ha):
                caught.append(
                    f"crop_growth DryYield {final_dry:.6f} differs from final stats {dry_t_ha:.6f}"
                )
        return AdapterResult(
            planting_date=planting,
            harvest_date=harvest,
            has_finished=True,
            yield_t_ha_raw=dry_t_ha,
            yield_kg_ha=yield_kg_ha,
            seasonal_irrigation_mm=seasonal_irr,
            raw=raw,
            trajectory=traj,
            warnings=caught,
        )
