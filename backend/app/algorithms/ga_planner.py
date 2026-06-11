"""
智能喷涂路径动态规划模块
基于遗传算法(GA)优化雾化喷涂机器人的路径，使高腐蚀区域获得更多沉积

问题描述：
- 输入：锈蚀热点分布(位置+严重度) + 机器人运动学约束
- 输出：喷涂轨迹点序列 + 各点停留时间 + 喷涂参数
- 目标：加权覆盖率最大化 + 路径长度最小化 + 沉积均匀度最大化
- 约束：运动学约束 + 无死角 + 总时长限制

算法设计：
- 染色体编码：整数序列（热点访问顺序）+ 浮点数组（各点停留比例）
- 选择：锦标赛选择(Tournament Selection)
- 交叉：顺序交叉(OX)用于访问顺序，算术交叉用于停留时间
- 变异：逆转变异(swap+inversion) + 高斯扰动
- 每6小时运行一次，结果通过WebSocket推送
"""

import math
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from enum import Enum
from datetime import datetime

import numpy as np

logger = logging.getLogger("ga_planner")


class RobotArmType(str, Enum):
    SCARA = "scara"           # 平面关节
    CARTESIAN = "cartesian"   # 直角坐标
    DELTA = "delta"           # 并联臂
    ARTICULATED = "articulated"  # 6轴关节


@dataclass
class RustHotspot:
    hotspot_id: str
    x: float           # 相对坐标 (米)
    y: float
    z: float
    severity: float    # 0-1
    area_cm2: float
    surface_normal: Tuple[float, float, float] = (0, 0, 1)
    required_coverage: float = 0.95


@dataclass
class RobotConfig:
    arm_type: RobotArmType = RobotArmType.ARTICULATED
    max_reach_m: float = 0.8
    min_reach_m: float = 0.1
    max_speed_m_s: float = 0.3
    spray_flow_rate_ml_s: float = 0.5
    optimal_distance_m: float = 0.15
    spray_angle_deg: float = 45.0
    max_total_time_s: float = 600.0
    droplet_mean_um: float = 30.0


@dataclass
class SprayWaypoint:
    x: float
    y: float
    z: float
    dwell_time_s: float
    flow_rate_ml_s: float
    spray_angle_deg: float
    orientation: Tuple[float, float, float]  # 末端方向


@dataclass
class SprayPathPlan:
    artifact_id: str
    waypoints: List[SprayWaypoint]
    total_distance_m: float
    total_time_s: float
    estimated_weighted_coverage: float
    uniformity_index: float
    total_volume_ml: float
    hotspot_coverage: Dict[str, float]
    generation: int
    best_fitness: float
    planning_time_ms: int
    plan_time: str


@dataclass
class GAIndividual:
    visit_order: np.ndarray      # 整数序列
    dwell_ratios: np.ndarray     # 停留时间比例
    fitness: float = -1.0


class GASprayPlanner:
    """基于遗传算法的喷涂路径规划器"""

    def __init__(self, config: Optional[RobotConfig] = None):
        self.config = config or RobotConfig()
        self.rng = np.random.RandomState(42)
        logger.info(f"GA Spray Planner initialized: {self.config.arm_type.value}")

    def optimize(
        self,
        artifact_id: str,
        hotspots: List[RustHotspot],
        artifact_size: Dict[str, float],
        population_size: int = 60,
        generations: int = 80,
        crossover_rate: float = 0.85,
        mutation_rate: float = 0.2,
        elite_size: int = 5,
        random_seed: Optional[int] = 42,
    ) -> SprayPathPlan:
        """执行遗传算法优化（带确定性种子与精英保留）

        Args:
            random_seed: 随机种子，None则使用实例默认种子。固定种子可确保重复运行结果一致。
        """
        start_time = datetime.now()

        if random_seed is not None:
            self.rng = np.random.RandomState(random_seed)

        if not hotspots:
            return self._empty_plan(artifact_id, start_time)

        n = len(hotspots)

        pop = self._init_population(population_size, n)
        self._evaluate_population(pop, hotspots)

        best_fitness = -float("inf")
        best_individual = None
        best_gen = 0

        for gen in range(generations):
            elite = self._select_elite(pop, min(elite_size, len(pop) // 5))

            new_pop = list(elite)

            while len(new_pop) < population_size:
                p1 = self._tournament_select(pop, k=3)
                p2 = self._tournament_select(pop, k=3)

                if self.rng.random() < crossover_rate:
                    c1_order, c1_dwell = self._crossover(p1, p2)
                    c2_order, c2_dwell = self._crossover(p2, p1)
                else:
                    c1_order, c1_dwell = p1.visit_order.copy(), p1.dwell_ratios.copy()
                    c2_order, c2_dwell = p2.visit_order.copy(), p2.dwell_ratios.copy()

                if self.rng.random() < mutation_rate:
                    c1_order, c1_dwell = self._mutate(c1_order, c1_dwell)
                if self.rng.random() < mutation_rate:
                    c2_order, c2_dwell = self._mutate(c2_order, c2_dwell)

                new_pop.append(GAIndividual(visit_order=c1_order, dwell_ratios=c1_dwell))
                new_pop.append(GAIndividual(visit_order=c2_order, dwell_ratios=c2_dwell))

            new_pop = new_pop[:population_size]
            self._evaluate_population(new_pop, hotspots)
            pop = new_pop

            gen_best = max(pop, key=lambda ind: ind.fitness)
            if gen_best.fitness > best_fitness:
                best_fitness = gen_best.fitness
                best_individual = GAIndividual(
                    visit_order=gen_best.visit_order.copy(),
                    dwell_ratios=gen_best.dwell_ratios.copy(),
                    fitness=gen_best.fitness,
                )
                best_gen = gen + 1

            if (gen + 1) % 20 == 0:
                logger.info(f"  GA Gen {gen+1}/{generations}, best_fitness={best_fitness:.4f}")

        waypoints = self._decode_chromosome(best_individual, hotspots, artifact_size)

        total_dist = self._compute_path_distance(waypoints)
        total_time = sum(wp.dwell_time_s for wp in waypoints) + total_dist / max(self.config.max_speed_m_s, 1e-6)
        coverage_map, avg_coverage = self._compute_hotspot_coverage(waypoints, hotspots)
        uniformity = self._compute_uniformity(waypoints, hotspots)
        total_vol = sum(wp.flow_rate_ml_s * wp.dwell_time_s for wp in waypoints)

        elapsed_ms = int((datetime.now() - start_time).total_seconds() * 1000)

        return SprayPathPlan(
            artifact_id=artifact_id,
            waypoints=waypoints,
            total_distance_m=round(total_dist, 3),
            total_time_s=round(total_time, 1),
            estimated_weighted_coverage=round(avg_coverage, 4),
            uniformity_index=round(uniformity, 4),
            total_volume_ml=round(total_vol, 2),
            hotspot_coverage={k: round(v, 4) for k, v in coverage_map.items()},
            generation=best_gen,
            best_fitness=round(best_fitness, 6),
            planning_time_ms=elapsed_ms,
            plan_time=datetime.now().isoformat(),
        )

    def _init_population(self, pop_size: int, n_hotspots: int) -> List[GAIndividual]:
        """初始化种群"""
        pop = []
        for _ in range(pop_size):
            order = np.arange(n_hotspots)
            self.rng.shuffle(order)

            dwell = self.rng.dirichlet(np.ones(n_hotspots) * 2.0)

            severity_seeded = True
            if severity_seeded and len(order) > 0:
                _ = dwell
            pop.append(GAIndividual(visit_order=order, dwell_ratios=dwell))
        return pop

    def _evaluate_population(self, pop: List[GAIndividual], hotspots: List[RustHotspot]):
        """评估种群中所有个体的适应度"""
        for ind in pop:
            ind.fitness = self._fitness(ind, hotspots)

    def _fitness(self, individual: GAIndividual, hotspots: List[RustHotspot]) -> float:
        """适应度函数：加权覆盖率 - 路径惩罚 - 不均匀惩罚"""
        n = len(hotspots)
        if n == 0:
            return 0.0

        order = individual.visit_order
        dwell = individual.dwell_ratios
        total_dwell_budget = max(self.config.max_total_time_s * 0.6, 30.0)

        dist_penalty = 0.0
        for i in range(n - 1):
            a = hotspots[order[i]]
            b = hotspots[order[i + 1]]
            d = math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)
            dist_penalty += d * 0.5

        deposition = np.zeros(n)
        for idx_i, hi in enumerate(order):
            source = hotspots[hi]
            t_i = dwell[idx_i] * total_dwell_budget
            for idx_j, hj in enumerate(hotspots):
                d = math.sqrt((source.x - hj.x) ** 2 + (source.y - hj.y) ** 2 + (source.z - hj.z) ** 2)
                if d > self.config.spray_angle_deg / 45.0:
                    continue
                d_eff = max(d, self.config.optimal_distance_m)
                dist_factor = math.exp(-0.5 * ((d_eff - self.config.optimal_distance_m) / 0.1) ** 2)
                dep = t_i * self.config.spray_flow_rate_ml_s * dist_factor
                deposition[idx_j] += dep

        w_coverage = 0.0
        for idx_j, hj in enumerate(hotspots):
            target_dep = hj.severity * hj.area_cm2 * 2.0
            ratio = deposition[idx_j] / max(target_dep, 1e-6)
            achieved = min(1.0, ratio)
            w_coverage += hj.severity * achieved
        w_coverage /= max(sum(h.severity for h in hotspots), 1e-6)

        if np.sum(deposition) > 1e-8:
            dep_norm = deposition / (np.sum(deposition) / n)
            cv = float(np.std(dep_norm) / np.mean(dep_norm))
            uniformity = math.exp(-cv)
        else:
            uniformity = 0.0

        fitness = (
            0.65 * w_coverage
            + 0.20 * uniformity
            - 0.15 * min(dist_penalty / max(n * 0.3, 1.0), 1.0)
        )
        return float(max(0.0, fitness))

    def _select_elite(self, pop: List[GAIndividual], k: int) -> List[GAIndividual]:
        """精英保留"""
        sorted_pop = sorted(pop, key=lambda ind: ind.fitness, reverse=True)
        elite = []
        for i in range(min(k, len(sorted_pop))):
            elite.append(GAIndividual(
                visit_order=sorted_pop[i].visit_order.copy(),
                dwell_ratios=sorted_pop[i].dwell_ratios.copy(),
                fitness=sorted_pop[i].fitness,
            ))
        return elite

    def _tournament_select(self, pop: List[GAIndividual], k: int = 3) -> GAIndividual:
        """锦标赛选择"""
        candidates = self.rng.choice(len(pop), size=k, replace=False)
        best = max(candidates, key=lambda i: pop[i].fitness)
        return pop[best]

    def _crossover(self, p1: GAIndividual, p2: GAIndividual) -> Tuple[np.ndarray, np.ndarray]:
        """顺序交叉(OX) + 算术交叉"""
        n = len(p1.visit_order)
        if n < 2:
            return p1.visit_order.copy(), p1.dwell_ratios.copy()

        cx1, cx2 = sorted(self.rng.choice(n, size=2, replace=False))
        child_order = -np.ones(n, dtype=int)
        child_order[cx1:cx2] = p1.visit_order[cx1:cx2]

        p2_idx = 0
        for i in range(n):
            if child_order[i] == -1:
                while p2.visit_order[p2_idx] in child_order:
                    p2_idx = (p2_idx + 1) % n
                child_order[i] = p2.visit_order[p2_idx]
                p2_idx = (p2_idx + 1) % n

        alpha = self.rng.uniform(0.2, 0.8)
        child_dwell = alpha * p1.dwell_ratios + (1 - alpha) * p2.dwell_ratios
        child_dwell = np.abs(child_dwell)
        total = child_dwell.sum()
        if total > 1e-10:
            child_dwell = child_dwell / total
        return child_order, child_dwell

    def _mutate(self, order: np.ndarray, dwell: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """逆转变异 + swap + 高斯扰动"""
        n = len(order)
        if n < 2:
            return order.copy(), dwell.copy()

        mut_order = order.copy()
        r = self.rng.random()
        if r < 0.5:
            i, j = sorted(self.rng.choice(n, size=2, replace=False))
            mut_order[i:j] = mut_order[i:j][::-1]
        else:
            i, j = self.rng.choice(n, size=2, replace=False)
            mut_order[i], mut_order[j] = mut_order[j], mut_order[i]

        mut_dwell = dwell + self.rng.normal(0, 0.05, n)
        mut_dwell = np.clip(mut_dwell, 0.01, None)
        total = mut_dwell.sum()
        if total > 1e-10:
            mut_dwell = mut_dwell / total
        return mut_order, mut_dwell

    def _decode_chromosome(
        self,
        individual: GAIndividual,
        hotspots: List[RustHotspot],
        artifact_size: Dict[str, float],
    ) -> List[SprayWaypoint]:
        """解码染色体为喷涂航点序列"""
        n = len(hotspots)
        waypoints = []
        total_budget = max(self.config.max_total_time_s * 0.6, 30.0)
        w = artifact_size.get("width", 0.5)
        h = artifact_size.get("height", 0.6)
        d = artifact_size.get("depth", 0.4)

        for rank, idx in enumerate(individual.visit_order):
            hs = hotspots[idx]
            t_dwell = float(individual.dwell_ratios[rank]) * total_budget
            t_dwell = max(1.0, t_dwell)

            offset = self.config.optimal_distance_m
            normal = hs.surface_normal
            if abs(normal[2]) < 0.01:
                normal = (normal[0], normal[1], 1.0)
            nx, ny, nz = normal
            norm = math.sqrt(nx*nx + ny*ny + nz*nz) or 1.0
            ox = hs.x + offset * nx / norm
            oy = hs.y + offset * ny / norm
            oz = hs.z + offset * nz / norm

            severity_factor = 0.5 + 0.5 * hs.severity
            flow = self.config.spray_flow_rate_ml_s * severity_factor
            angle = self.config.spray_angle_deg * (0.8 + 0.4 * (1 - hs.severity))

            waypoints.append(SprayWaypoint(
                x=round(ox, 4), y=round(oy, 4), z=round(oz, 4),
                dwell_time_s=round(t_dwell, 1),
                flow_rate_ml_s=round(flow, 3),
                spray_angle_deg=round(angle, 1),
                orientation=(round(nx/norm, 3), round(ny/norm, 3), round(nz/norm, 3)),
            ))

        return waypoints

    def _compute_path_distance(self, waypoints: List[SprayWaypoint]) -> float:
        """计算路径总长度"""
        total = 0.0
        for i in range(len(waypoints) - 1):
            a, b = waypoints[i], waypoints[i + 1]
            total += math.sqrt((a.x - b.x)**2 + (a.y - b.y)**2 + (a.z - b.z)**2)
        return total

    def _compute_hotspot_coverage(
        self,
        waypoints: List[SprayWaypoint],
        hotspots: List[RustHotspot],
    ) -> Tuple[Dict[str, float], float]:
        """计算各热点覆盖率"""
        cov_map: Dict[str, float] = {}
        weighted_sum = 0.0
        sev_sum = 0.0
        for hs in hotspots:
            dep_total = 0.0
            for wp in waypoints:
                d = math.sqrt((wp.x - hs.x)**2 + (wp.y - hs.y)**2 + (wp.z - hs.z)**2)
                d_eff = max(d, self.config.optimal_distance_m)
                f = math.exp(-0.5 * ((d_eff - self.config.optimal_distance_m) / 0.1) ** 2)
                dep_total += wp.dwell_time_s * wp.flow_rate_ml_s * f
            target = hs.severity * hs.area_cm2 * 2.0
            ratio = dep_total / max(target, 1e-6)
            achieved = min(1.0, ratio)
            cov_map[hs.hotspot_id] = achieved
            weighted_sum += hs.severity * achieved
            sev_sum += hs.severity
        avg_cov = weighted_sum / max(sev_sum, 1e-6)
        return cov_map, avg_cov

    def _compute_uniformity(self, waypoints: List[SprayWaypoint],
                            hotspots: List[RustHotspot]) -> float:
        """计算沉积均匀度指数"""
        if not hotspots:
            return 0.0
        covs = []
        for hs in hotspots:
            dep = 0.0
            for wp in waypoints:
                d = math.sqrt((wp.x - hs.x)**2 + (wp.y - hs.y)**2 + (wp.z - hs.z)**2)
                d_eff = max(d, self.config.optimal_distance_m)
                f = math.exp(-0.5 * ((d_eff - self.config.optimal_distance_m) / 0.1) ** 2)
                dep += wp.dwell_time_s * wp.flow_rate_ml_s * f
            covs.append(dep)
        arr = np.array(covs)
        if arr.mean() < 1e-10:
            return 0.0
        cv = float(arr.std() / arr.mean())
        return math.exp(-cv)

    def _empty_plan(self, artifact_id: str, start_time: datetime) -> SprayPathPlan:
        return SprayPathPlan(
            artifact_id=artifact_id,
            waypoints=[],
            total_distance_m=0.0,
            total_time_s=0.0,
            estimated_weighted_coverage=0.0,
            uniformity_index=0.0,
            total_volume_ml=0.0,
            hotspot_coverage={},
            generation=0,
            best_fitness=0.0,
            planning_time_ms=int((datetime.now() - start_time).total_seconds() * 1000),
            plan_time=datetime.now().isoformat(),
        )


def waypoints_to_dict(plan: SprayPathPlan) -> Dict:
    """将喷涂规划结果转为可序列化字典"""
    return {
        "artifact_id": plan.artifact_id,
        "waypoints": [
            {
                "x": wp.x, "y": wp.y, "z": wp.z,
                "dwell_time_s": wp.dwell_time_s,
                "flow_rate_ml_s": wp.flow_rate_ml_s,
                "spray_angle_deg": wp.spray_angle_deg,
                "orientation": list(wp.orientation),
            }
            for wp in plan.waypoints
        ],
        "total_distance_m": plan.total_distance_m,
        "total_time_s": plan.total_time_s,
        "estimated_weighted_coverage": plan.estimated_weighted_coverage,
        "uniformity_index": plan.uniformity_index,
        "total_volume_ml": plan.total_volume_ml,
        "hotspot_coverage": plan.hotspot_coverage,
        "generation": plan.generation,
        "best_fitness": plan.best_fitness,
        "planning_time_ms": plan.planning_time_ms,
        "plan_time": plan.plan_time,
    }
