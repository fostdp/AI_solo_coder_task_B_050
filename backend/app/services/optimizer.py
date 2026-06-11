"""
Optimizer Service (微服务4)
职责：
  1. 从 Redis Stream:predictions 消费预测结果
  2. 基于 CFD 简化模型的缓蚀剂雾化喷涂覆盖优化
  3. 生成喷涂路径、喷嘴位置、用量估算
  4. 发布优化结果到 Stream

数据流：Redis Stream:predictions -> CFD喷涂优化 -> 喷涂方案
"""

import asyncio
import json
import logging
import numpy as np
from datetime import datetime
from typing import Dict, Optional, List, Tuple
from dataclasses import dataclass, field
from enum import Enum

from ..config import get_settings
from ..streams import RedisStreamManager, parse_stream_message

logger = logging.getLogger("optimizer")
settings = get_settings()


class InhibitorType(str, Enum):
    BTA = "BTA"
    AMT = "AMT"
    MBO = "MBO"


INHIBITOR_PROPERTIES = {
    InhibitorType.BTA: {
        "molecular_weight": 119.12,
        "vapor_pressure_kpa": 1.3e-5,
        "solubility_g_L": 25.0,
        "adsorption_energy_kJ_mol": -65.0,
        "surface_tension_mN_m": 58.0,
        "viscosity_mPa_s": 1.8,
        "density_g_cm3": 1.25,
        "optimal_concentration_mM": 10.0,
        "coverage_efficiency_base": 0.85,
        "color": "#00aaff"
    },
    InhibitorType.AMT: {
        "molecular_weight": 150.22,
        "vapor_pressure_kpa": 8.5e-6,
        "solubility_g_L": 40.0,
        "adsorption_energy_kJ_mol": -78.0,
        "surface_tension_mN_m": 52.0,
        "viscosity_mPa_s": 2.1,
        "density_g_cm3": 1.32,
        "optimal_concentration_mM": 15.0,
        "coverage_efficiency_base": 0.92,
        "color": "#00ff88"
    },
    InhibitorType.MBO: {
        "molecular_weight": 150.22,
        "vapor_pressure_kpa": 5.2e-6,
        "solubility_g_L": 18.0,
        "adsorption_energy_kJ_mol": -85.0,
        "surface_tension_mN_m": 55.0,
        "viscosity_mPa_s": 2.4,
        "density_g_cm3": 1.30,
        "optimal_concentration_mM": 8.0,
        "coverage_efficiency_base": 0.95,
        "color": "#ffaa00"
    }
}


@dataclass
class NozzlePosition:
    x: float
    y: float
    z: float
    theta_x: float
    theta_y: float
    spray_angle_deg: float
    pressure_bar: float
    dwell_time_s: float


@dataclass
class SprayZoneResult:
    zone_id: str
    center: Dict[str, float]
    required_coverage: float
    predicted_coverage: float
    estimated_volume_ml: float
    spray_time_s: float
    inhibitor_type: str
    pass_count: int


@dataclass
class OptimizationResult:
    artifact_id: str
    inhibitor_type: InhibitorType
    total_volume_ml: float
    total_spray_time_s: float
    estimated_coverage: float
    nozzle_positions: List[NozzlePosition]
    zone_results: List[SprayZoneResult]
    spray_path: List[Dict]
    cfd_simulation_summary: Dict = field(default_factory=dict)


class SprayOptimizerService:
    """CFD简化喷涂优化微服务"""

    def __init__(self, stream_manager: Optional[RedisStreamManager] = None):
        self.stream_mgr = stream_manager
        self._prediction_stream = settings.REDIS_STREAM_PREDICTIONS
        self._alert_stream = settings.REDIS_STREAM_ALERTS
        self._group = "group:optimizer"
        self._consumer_name = f"optimizer_{id(self)}"

        self.env_temperature = 22.0
        self.env_humidity = 45.0
        self.env_pressure = 101.3

        self._running = False
        self._stats = {
            "optimized": 0,
            "failed": 0,
            "last_ts": None
        }

    async def start(self):
        if self.stream_mgr:
            await self.stream_mgr.ensure_group(self._prediction_stream, self._group)
        self._running = True
        logger.info("Spray Optimizer service started")

    async def stop(self):
        self._running = False
        logger.info("Spray Optimizer service stopped")

    async def run_loop(self):
        await self.start()
        while self._running:
            try:
                if not self.stream_mgr:
                    await asyncio.sleep(1)
                    continue

                messages = await self.stream_mgr.consume_group(
                    self._prediction_stream,
                    self._group,
                    self._consumer_name,
                    count=2,
                    block_ms=3000
                )

                for stream_name, stream_msgs in messages:
                    for msg in stream_msgs:
                        try:
                            parsed = parse_stream_message(msg)
                            await self._process_prediction(parsed)
                            await self.stream_mgr.ack(
                                self._prediction_stream, self._group, parsed["_id"]
                            )
                            self._stats["optimized"] += 1
                            self._stats["last_ts"] = datetime.utcnow()
                        except Exception as e:
                            self._stats["failed"] += 1
                            logger.exception(f"Spray optimization failed: {e}")

                if not messages:
                    await asyncio.sleep(0.5)

            except Exception as e:
                logger.exception(f"Optimizer loop error: {e}")
                await asyncio.sleep(1)

    async def _process_prediction(self, msg: Dict):
        artifact_id = msg.get("artifact_id", "")
        risk_level = int(msg.get("risk_level", 0))

        if risk_level < 3:
            logger.debug(
                f"Skipping optimization for {artifact_id}, "
                f"risk_level={risk_level} (threshold: 3)"
            )
            return

        risk_zones_raw = msg.get("risk_zones", "[]")
        if isinstance(risk_zones_raw, str):
            try:
                risk_zones = json.loads(risk_zones_raw)
            except json.JSONDecodeError:
                risk_zones = []
        else:
            risk_zones = risk_zones_raw or []

        if not risk_zones:
            return

        result = self.optimize(
            artifact_id=artifact_id,
            target_zones=risk_zones,
            artifact_size={"width": 0.5, "height": 0.6, "depth": 0.4},
            inhibitor_type=InhibitorType.BTA
        )

        logger.info(
            f"Spray optimized for {artifact_id}: "
            f"volume={result.total_volume_ml:.2f}ml, "
            f"time={result.total_spray_time_s:.1f}s, "
            f"coverage={result.estimated_coverage:.2%}"
        )

    def optimize(
        self,
        artifact_id: str,
        target_zones: List[Dict],
        artifact_size: Dict[str, float],
        inhibitor_type: InhibitorType = InhibitorType.BTA,
        required_coverage: float = 0.95,
        nozzle_count: int = 4,
        max_nozzle_positions: int = 16
    ) -> OptimizationResult:
        logger.info(f"Optimizing spray plan for {artifact_id} with {inhibitor_type}")

        props = INHIBITOR_PROPERTIES[inhibitor_type]
        surface_points = self._generate_surface_discretization(
            artifact_size, target_zones
        )

        nozzle_candidates = self._generate_nozzle_candidates(
            artifact_size, nozzle_count
        )

        nozzle_positions, coverage_matrix = self._optimize_placement(
            nozzle_candidates,
            surface_points,
            props,
            required_coverage,
            max_nozzle_positions
        )

        zone_results = self._calculate_zone_metrics(
            surface_points, target_zones, nozzle_positions,
            props, coverage_matrix, artifact_size
        )

        total_volume = sum(z.estimated_volume_ml for z in zone_results)
        total_time = sum(z.spray_time_s for z in zone_results)
        avg_coverage = np.mean([z.predicted_coverage for z in zone_results])

        spray_path = self._generate_spray_path(nozzle_positions, zone_results)

        return OptimizationResult(
            artifact_id=artifact_id,
            inhibitor_type=inhibitor_type,
            total_volume_ml=float(total_volume),
            total_spray_time_s=float(total_time),
            estimated_coverage=float(min(avg_coverage, 1.0)),
            nozzle_positions=nozzle_positions,
            zone_results=zone_results,
            spray_path=spray_path,
            cfd_simulation_summary={
                "env_temperature": self.env_temperature,
                "env_humidity": self.env_humidity,
                "nozzle_candidates_evaluated": len(nozzle_candidates),
                "droplet_mean_diameter_um": self._estimate_droplet_size(props),
                "evaporation_rate_coeff": self._estimate_evaporation(props),
                "deposition_efficiency": props["coverage_efficiency_base"]
            }
        )

    def _project_point_to_surface(
        self, cx, cy, cz, w, h, d
    ) -> Tuple[float, float, float, float, float, float]:
        hx, hy, hz = w / 2, h / 2, d / 2
        surfaces = [
            (abs(cz + hz), 'front',  cx, cy,   -hz, 0, 0, -1),
            (abs(cz - hz), 'back',   cx, cy,    hz, 0, 0,  1),
            (abs(cy + hy), 'bottom', cx,  -hy,  cz, 0, -1, 0),
            (abs(cy - hy), 'top',    cx,   hy,  cz, 0,  1, 0),
            (abs(cx + hx), 'left',  -hx,  cy,  cz, -1, 0, 0),
            (abs(cx - hx), 'right',  hx,  cy,  cz,  1, 0, 0),
        ]
        surfaces.sort(key=lambda x: x[0])
        _, _, px, py, pz, nx, ny, nz = surfaces[0]
        cx_c = max(-hx, min(hx, px))
        cy_c = max(-hy, min(hy, py))
        cz_c = max(-hz, min(hz, pz))
        return cx_c, cy_c, cz_c, nx, ny, nz

    def _generate_surface_discretization(
        self, size: Dict[str, float], target_zones: List[Dict]
    ):
        points = []
        w = size.get("width", 0.5)
        h = size.get("height", 0.6)
        d = size.get("depth", 0.4)

        n_per_face = 20
        zone_map = {}
        for zi, z in enumerate(target_zones):
            c = z.get("center", {"x": 0, "y": 0, "z": 0})
            r = z.get("radius", 0.05)
            pcx, pcy, pcz, _, _, _ = self._project_point_to_surface(
                c.get("x", 0), c.get("y", 0), c.get("z", 0), w, h, d
            )
            zone_map[f"Z{zi+1:02d}"] = (pcx, pcy, pcz, r)

        def add_face(pts, ox, oy, oz, dux, duy, duz, dvx, dvy, dvz, nx, ny, nz):
            for i in range(n_per_face):
                for j in range(n_per_face):
                    u = i / (n_per_face - 1)
                    v = j / (n_per_face - 1)
                    x = ox + u * dux + v * dvx
                    y = oy + u * duy + v * dvy
                    z = oz + u * duz + v * dvz
                    cx = x - w / 2
                    cy = y - h / 2
                    cz = z - d / 2
                    curvature = 0.01 * np.sin(np.pi * u) * np.sin(np.pi * v)
                    zone_id = "GEN"
                    is_target = False
                    for zid, (zx, zy, zz, zr) in zone_map.items():
                        dist = np.sqrt((cx - zx) ** 2 + (cy - zy) ** 2 + (cz - zz) ** 2)
                        if dist < zr:
                            zone_id = zid
                            is_target = True
                            break
                    pts.append({
                        "x": float(cx), "y": float(cy), "z": float(cz),
                        "nx": nx, "ny": ny, "nz": nz,
                        "curvature": curvature, "zone_id": zone_id,
                        "is_target": is_target
                    })

        add_face(points, 0, 0, 0,  w, 0, 0,  0, h, 0,  0, 0, -1)
        add_face(points, 0, 0, d,  w, 0, 0,  0, h, 0,  0, 0,  1)
        add_face(points, 0, 0, 0,  w, 0, 0,  0, 0, d,  0, -1, 0)
        add_face(points, 0, h, 0,  w, 0, 0,  0, 0, d,  0,  1, 0)
        add_face(points, 0, 0, 0,  0, h, 0,  0, 0, d,  -1, 0, 0)
        add_face(points, w, 0, 0,  0, h, 0,  0, 0, d,   1, 0, 0)

        return points

    def _generate_nozzle_candidates(
        self, size: Dict[str, float], n_per_axis: int
    ) -> List[NozzlePosition]:
        candidates = []
        w = size.get("width", 0.5)
        h = size.get("height", 0.6)
        d = size.get("depth", 0.4)
        hx, hy, hz = w / 2, h / 2, d / 2
        standoff = 0.25
        angles = [-20, 0, 20]

        xs = np.linspace(-hx - standoff, hx + standoff, n_per_axis)
        ys = np.linspace(-hy - 0.05, hy + standoff, n_per_axis)
        zs = np.linspace(-hz - standoff, hz + standoff, n_per_axis)
        for cx in xs:
            for cz in zs:
                for ax in angles:
                    for ay in angles:
                        candidates.append(NozzlePosition(
                            x=float(cx), y=float(hy + standoff), z=float(cz),
                            theta_x=float(ax), theta_y=float(ay),
                            spray_angle_deg=45.0, pressure_bar=2.5, dwell_time_s=2.0
                        ))

        ys_mid = np.linspace(-hy + 0.05, hy - 0.05, n_per_axis)
        for cx in [-hx - standoff, hx + standoff]:
            for cy in ys_mid:
                for ax in angles:
                    for ay in angles:
                        candidates.append(NozzlePosition(
                            x=float(cx), y=float(cy), z=float(0),
                            theta_x=float(ax), theta_y=float(ay),
                            spray_angle_deg=45.0, pressure_bar=2.5, dwell_time_s=2.0
                        ))
        for cz in [-hz - standoff, hz + standoff]:
            for cy in ys_mid:
                for ax in angles:
                    for ay in angles:
                        candidates.append(NozzlePosition(
                            x=float(0), y=float(cy), z=float(cz),
                            theta_x=float(ax), theta_y=float(ay),
                            spray_angle_deg=45.0, pressure_bar=2.5, dwell_time_s=2.0
                        ))

        return candidates

    def _optimize_placement(
        self, candidates: List[NozzlePosition], points,
        props: Dict, required_coverage: float, max_positions: int
    ) -> Tuple[List[NozzlePosition], np.ndarray]:
        target_points = [p for p in points if p["is_target"]]
        if not target_points:
            target_points = points

        n_candidates = len(candidates)
        n_points = len(target_points)

        coverage_matrix = np.zeros((n_candidates, n_points))
        cost_vector = np.zeros(n_candidates)

        for ci, nozzle in enumerate(candidates):
            for pi, point in enumerate(target_points):
                coverage_matrix[ci, pi] = self._compute_nozzle_point_coverage(
                    nozzle, point, props
                )
            coverage_ratio = np.sum(coverage_matrix[ci] > 0.05) / n_points
            cost_vector[ci] = nozzle.dwell_time_s * (1.0 - 0.5 * coverage_ratio)

        selected = []
        remaining_mask = np.ones(n_points, dtype=bool)
        current_coverage = np.zeros(n_points)
        used = np.zeros(n_candidates, dtype=bool)

        while len(selected) < max_positions:
            uncovered_count = np.sum(remaining_mask)
            if uncovered_count == 0:
                break

            avg_uncovered = np.mean(current_coverage[remaining_mask])
            if avg_uncovered >= required_coverage and uncovered_count < n_points * 0.1:
                break

            best_score = -np.inf
            best_idx = -1

            for ci in range(n_candidates):
                if used[ci]:
                    continue
                new_coverage = np.minimum(
                    current_coverage + coverage_matrix[ci] * remaining_mask,
                    1.0
                )
                marginal = (np.sum(new_coverage[remaining_mask]) -
                            np.sum(current_coverage[remaining_mask]))
                score = marginal / (cost_vector[ci] + 0.1)

                if score > best_score:
                    best_score = score
                    best_idx = ci

            if best_idx < 0:
                break

            used[best_idx] = True
            selected.append(candidates[best_idx])
            current_coverage = np.minimum(
                current_coverage + coverage_matrix[best_idx], 1.0
            )
            remaining_mask = current_coverage < required_coverage

        final_coverage_matrix = coverage_matrix[used]

        return selected, final_coverage_matrix

    def _compute_nozzle_point_coverage(
        self, nozzle: NozzlePosition, point: Dict, props: Dict
    ) -> float:
        dx = point["x"] - nozzle.x
        dy = point["y"] - nozzle.y
        dz = point["z"] - nozzle.z
        dist = np.sqrt(dx * dx + dy * dy + dz * dz)

        if dist < 0.05 or dist > 1.5:
            return 0.0

        ndx = -nozzle.x
        ndy = -nozzle.y
        ndz = -nozzle.z
        nd = np.sqrt(ndx**2 + ndy**2 + ndz**2)
        if nd > 1e-9:
            ndx, ndy, ndz = ndx/nd, ndy/nd, ndz/nd
        else:
            ndx, ndy, ndz = 0, -1, 0

        rot_x = np.radians(nozzle.theta_x)
        rot_y = np.radians(nozzle.theta_y)
        rx = np.array([
            [1, 0, 0],
            [0, np.cos(rot_x), -np.sin(rot_x)],
            [0, np.sin(rot_x), np.cos(rot_x)]
        ])
        rz = np.array([
            [np.cos(rot_y), -np.sin(rot_y), 0],
            [np.sin(rot_y), np.cos(rot_y), 0],
            [0, 0, 1]
        ])
        default_dir = np.array([ndx, ndy, ndz])
        rot_dir = rz @ rx @ default_dir
        dir_x, dir_y, dir_z = rot_dir[0], rot_dir[1], rot_dir[2]
        norm_dir = np.sqrt(dir_x ** 2 + dir_y ** 2 + dir_z ** 2)
        if norm_dir < 1e-9:
            dir_x, dir_y, dir_z = ndx, ndy, ndz
        else:
            dir_x /= norm_dir
            dir_y /= norm_dir
            dir_z /= norm_dir

        dot = (dx * dir_x + dy * dir_y + dz * dir_z) / dist
        if dot <= 0:
            return 0.0

        angle_off_axis = np.degrees(np.arccos(min(dot, 1.0)))
        if angle_off_axis > nozzle.spray_angle_deg:
            return 0.0

        normal_dot = (-dx * point["nx"] + -dy * point["ny"] + -dz * point["nz"]) / (dist + 1e-9)
        normal_factor = max(0.0, normal_dot)

        radial_factor = np.exp(-2.0 * (angle_off_axis / nozzle.spray_angle_deg) ** 2)
        dist_factor = np.exp(-0.5 * dist / 0.5)

        curvature_penalty = np.exp(-3.0 * abs(point["curvature"]))
        evap_factor = self._estimate_evaporation(props) * dist / 1.0
        evap_factor = max(0.1, 1.0 - evap_factor)

        base = props["coverage_efficiency_base"]
        coverage = base * normal_factor * radial_factor * dist_factor * \
            curvature_penalty * evap_factor

        pressure_gain = 0.15 * np.log(nozzle.pressure_bar / 2.0 + 1.0)
        coverage *= (1.0 + pressure_gain)

        dwell_gain = np.sqrt(min(nozzle.dwell_time_s / 2.0, 4.0))
        coverage *= dwell_gain

        return float(min(coverage, 0.98))

    def _calculate_zone_metrics(
        self, points, target_zones: List[Dict],
        nozzles: List[NozzlePosition], props: Dict,
        coverage_matrix: np.ndarray, artifact_size=None
    ) -> List[SprayZoneResult]:
        results = []
        w = artifact_size.get("width", 0.5) if artifact_size else 0.5
        h = artifact_size.get("height", 0.6) if artifact_size else 0.6
        d = artifact_size.get("depth", 0.4) if artifact_size else 0.4

        for zi, zone in enumerate(target_zones):
            zid = f"Z{zi+1:02d}"
            z_points = [p for p in points if p["zone_id"] == zid]
            if not z_points:
                c = zone.get("center", {"x": 0, "y": 0, "z": 0})
                pcx, pcy, pcz, nx, ny, nz = self._project_point_to_surface(
                    c.get("x", 0), c.get("y", 0), c.get("z", 0), w, h, d
                )
                z_points = [{
                    "x": pcx, "y": pcy, "z": pcz,
                    "nx": nx, "ny": ny, "nz": nz,
                    "curvature": 0, "zone_id": zid, "is_target": True
                }]

            coverages = []
            for point in z_points:
                point_cov = 0.0
                for nozzle in nozzles:
                    point_cov = max(point_cov, self._compute_nozzle_point_coverage(
                        nozzle, point, props
                    ))
                coverages.append(point_cov)

            avg_cov = float(np.mean(coverages)) if coverages else 0.5
            r = zone.get("radius", 0.05)
            area_cm2 = np.pi * (r * 100) ** 2
            thickness_um = 1.5
            volume_ml = area_cm2 * thickness_um * 1e-4 / props["density_g_cm3"]
            volume_ml *= (1.0 + 0.3 * (1.0 - avg_cov))

            spray_time = len(nozzles) * 2.0 + 3.0 * (zi + 1)

            results.append(SprayZoneResult(
                zone_id=zid,
                center=zone.get("center", {"x": 0, "y": 0, "z": 0}),
                required_coverage=zone.get("required_coverage", 0.95),
                predicted_coverage=avg_cov,
                estimated_volume_ml=float(max(volume_ml, 0.1)),
                spray_time_s=float(spray_time),
                inhibitor_type=props.get("color", ""),
                pass_count=max(1, int(np.ceil((0.95 - avg_cov + 0.05) * 5)))
            ))

        return results

    def _generate_spray_path(
        self, nozzles: List[NozzlePosition], zones: List[SprayZoneResult]
    ) -> List[Dict]:
        path = []
        all_waypoints = []

        for z in zones:
            all_waypoints.append({
                "type": "zone",
                "zone_id": z.zone_id,
                "x": z.center.get("x", 0),
                "y": z.center.get("y", 0) + 0.25,
                "z": z.center.get("z", 0),
                "dwell": z.spray_time_s / len(nozzles),
                "volume": z.estimated_volume_ml / max(1, z.pass_count)
            })

        for i, n in enumerate(nozzles):
            all_waypoints.append({
                "type": "nozzle",
                "index": i,
                "x": n.x, "y": n.y, "z": n.z,
                "theta_x": n.theta_x,
                "theta_y": n.theta_y,
                "pressure": n.pressure_bar,
                "dwell": n.dwell_time_s
            })

        all_waypoints.sort(key=lambda w: (w["x"], w["y"], w["z"]))

        current = {"x": 0.5, "y": 0.5, "z": 0.5}
        for step_i, wp in enumerate(all_waypoints):
            move_vect = {
                "from": current.copy(),
                "to": {"x": wp["x"], "y": wp["y"], "z": wp["z"]},
                "step": step_i + 1,
                "action": "move"
            }
            path.append(move_vect)

            if wp.get("type") in ("zone", "nozzle"):
                path.append({
                    "step": step_i + 1,
                    "action": "spray",
                    "position": {"x": wp["x"], "y": wp["y"], "z": wp["z"]},
                    "dwell_s": wp.get("dwell", 2.0),
                    "volume_ml": wp.get("volume", 0.5),
                    "pressure_bar": wp.get("pressure", 2.5)
                })

            current = {"x": wp["x"], "y": wp["y"], "z": wp["z"]}

        return path

    def _estimate_droplet_size(self, props: Dict) -> float:
        st = props["surface_tension_mN_m"]
        mu = props["viscosity_mPa_s"]
        rho = props["density_g_cm3"] * 1000
        P = 2.5e5
        D32 = 500.0 * np.sqrt(st / (rho * P)) * (1 + 0.2 * mu / 2.0)
        return float(D32)

    def _estimate_evaporation(self, props: Dict) -> float:
        vp = props["vapor_pressure_kpa"]
        mw = props["molecular_weight"]
        R = 8.314
        T = self.env_temperature + 273.15
        RH = self.env_humidity / 100.0
        c_sat = vp * 1000 * mw / (R * T)
        evap_coeff = 1e-7 * c_sat * (1 - RH * 0.3) / mw
        return float(evap_coeff * 1e6)

    def get_stats(self) -> Dict:
        return {
            **self._stats,
            "is_running": self._running,
            "inhibitors": list(INHIBITOR_PROPERTIES.keys())
        }
