from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text, select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import logging

from ..database import get_db
from ..schemas.schemas import (
    BronzeArtifactRead, SensorRead, AlertRead, SprayTaskRead,
    PredictionRead, RealtimeStatus, StatisticsResponse,
    SprayTaskCreate, AlertAcknowledge, AlertResolve, ApiResponse,
    TrendDataPoint
)
from ..models.models import (
    BronzeArtifact, Sensor, Alert, InhibitorSprayTask, RustPrediction,
    ElectrochemicalNoiseData, MicroenvironmentData
)
from ..algorithms.spray_optimizer import (
    CFDSimplifiedSprayOptimizer, InhibitorType
)
from ..mqtt_processor import data_processor

router = APIRouter(prefix="/api", tags=["core"])
logger = logging.getLogger("api_router")


@router.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@router.get("/statistics", response_model=StatisticsResponse)
async def get_statistics(db: AsyncSession = Depends(get_db)):
    stats = StatisticsResponse()

    result = await db.execute(select(func.count()).select_from(BronzeArtifact))
    stats.total_artifacts = int(result.scalar() or 0)

    for level, col in [(1, "normal_count"), (2, "warning_count"), (3, "alert_count")]:
        r = await db.execute(
            select(func.count()).where(BronzeArtifact.status == level)
        )
        setattr(stats, col, int(r.scalar() or 0))

    r = await db.execute(
        select(func.count()).where(
            and_(Alert.resolved == False,
                 Alert.alert_time > datetime.utcnow() - timedelta(hours=24))
        )
    )
    stats.active_alerts_24h = int(r.scalar() or 0)

    r = await db.execute(
        select(func.count()).where(InhibitorSprayTask.status.in_([0, 1]))
    )
    stats.spray_tasks_pending = int(r.scalar() or 0)

    r = await db.execute(text("""
        SELECT AVG(noise_resistance) FROM (
            SELECT DISTINCT ON (artifact_id) artifact_id, noise_resistance
            FROM electrochemical_noise_data
            WHERE time > NOW() - INTERVAL '24 hours'
            ORDER BY artifact_id, time DESC
        ) sub
    """))
    stats.avg_noise_resistance = float(r.scalar() or 0)

    r = await db.execute(text("""
        SELECT AVG(chloride_concentration) FROM (
            SELECT DISTINCT ON (artifact_id) artifact_id, chloride_concentration
            FROM microenvironment_data
            WHERE time > NOW() - INTERVAL '24 hours'
            ORDER BY artifact_id, time DESC
        ) sub
    """))
    stats.avg_chloride = float(r.scalar() or 0)

    r = await db.execute(select(func.count()).where(Sensor.status == 1))
    stats.sensors_online = int(r.scalar() or 0)

    r = await db.execute(
        select(func.count()).where(
            func.date(RustPrediction.prediction_time) == datetime.utcnow().date()
        )
    )
    stats.predictions_today = int(r.scalar() or 0)

    return stats


@router.get("/artifacts", response_model=List[BronzeArtifactRead])
async def list_artifacts(
    skip: int = 0,
    limit: int = 50,
    dynasty: Optional[str] = None,
    status: Optional[int] = None,
    keyword: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    query = select(BronzeArtifact)
    conditions = []
    if dynasty:
        conditions.append(BronzeArtifact.dynasty == dynasty)
    if status is not None:
        conditions.append(BronzeArtifact.status == status)
    if keyword:
        conditions.append(or_(
            BronzeArtifact.name.ilike(f"%{keyword}%"),
            BronzeArtifact.artifact_id.ilike(f"%{keyword}%")
        ))
    if conditions:
        query = query.where(and_(*conditions))
    query = query.order_by(BronzeArtifact.artifact_id).offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/artifacts/{artifact_id}", response_model=BronzeArtifactRead)
async def get_artifact(artifact_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(BronzeArtifact).where(BronzeArtifact.artifact_id == artifact_id)
    )
    artifact = result.scalar_one_or_none()
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return artifact


@router.get("/artifacts/{artifact_id}/realtime", response_model=RealtimeStatus)
async def get_artifact_realtime(artifact_id: str, db: AsyncSession = Depends(get_db)):
    base_query = text("""
        SELECT
            a.artifact_id, a.name, a.dynasty, a.status, a.showcase_id,
            le.time, le.noise_resistance,
            lm.time, lm.temperature, lm.humidity,
            lm.chloride_concentration, lm.sulfur_dioxide,
            lp.eruption_probability, lp.risk_level
        FROM bronze_artifacts a
        LEFT JOIN LATERAL (
            SELECT time, noise_resistance
            FROM electrochemical_noise_data
            WHERE artifact_id = a.artifact_id ORDER BY time DESC LIMIT 1
        ) le ON TRUE
        LEFT JOIN LATERAL (
            SELECT time, temperature, humidity, chloride_concentration, sulfur_dioxide
            FROM microenvironment_data
            WHERE artifact_id = a.artifact_id ORDER BY time DESC LIMIT 1
        ) lm ON TRUE
        LEFT JOIN LATERAL (
            SELECT eruption_probability, risk_level
            FROM rust_predictions
            WHERE artifact_id = a.artifact_id ORDER BY prediction_time DESC LIMIT 1
        ) lp ON TRUE
        WHERE a.artifact_id = :aid
    """)
    result = await db.execute(base_query, {"aid": artifact_id})
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Artifact not found")

    return RealtimeStatus(
        artifact_id=row[0], name=row[1], dynasty=row[2],
        status=row[3], showcase_id=row[4],
        ecn_update_time=row[5], noise_resistance=row[6],
        menv_update_time=row[7], temperature=row[8], humidity=row[9],
        chloride_concentration=row[10], sulfur_dioxide=row[11],
        eruption_probability=row[12], risk_level=row[13]
    )


@router.get("/artifacts/realtime/all", response_model=List[RealtimeStatus])
async def list_realtime_status(
    status_filter: Optional[int] = None,
    limit: int = 200,
    db: AsyncSession = Depends(get_db)
):
    base_query = text("""
        SELECT
            a.artifact_id, a.name, a.dynasty, a.status, a.showcase_id,
            le.time, le.noise_resistance,
            lm.time, lm.temperature, lm.humidity,
            lm.chloride_concentration, lm.sulfur_dioxide,
            lp.eruption_probability, lp.risk_level
        FROM bronze_artifacts a
        LEFT JOIN LATERAL (
            SELECT time, noise_resistance
            FROM electrochemical_noise_data
            WHERE artifact_id = a.artifact_id ORDER BY time DESC LIMIT 1
        ) le ON TRUE
        LEFT JOIN LATERAL (
            SELECT time, temperature, humidity, chloride_concentration, sulfur_dioxide
            FROM microenvironment_data
            WHERE artifact_id = a.artifact_id ORDER BY time DESC LIMIT 1
        ) lm ON TRUE
        LEFT JOIN LATERAL (
            SELECT eruption_probability, risk_level
            FROM rust_predictions
            WHERE artifact_id = a.artifact_id ORDER BY prediction_time DESC LIMIT 1
        ) lp ON TRUE
        WHERE (:st IS NULL OR a.status = :st)
        ORDER BY a.status DESC, a.artifact_id
        LIMIT :lim
    """)
    result = await db.execute(base_query, {"st": status_filter, "lim": limit})
    rows = result.fetchall()

    items = []
    for row in rows:
        items.append(RealtimeStatus(
            artifact_id=row[0], name=row[1], dynasty=row[2],
            status=row[3], showcase_id=row[4],
            ecn_update_time=row[5], noise_resistance=row[6],
            menv_update_time=row[7], temperature=row[8], humidity=row[9],
            chloride_concentration=row[10], sulfur_dioxide=row[11],
            eruption_probability=row[12], risk_level=row[13]
        ))
    return items


@router.get("/artifacts/{artifact_id}/trends")
async def get_artifact_trends(
    artifact_id: str,
    metric: str = Query(default="noise_resistance",
                        description="noise_resistance, chloride_concentration, temperature, humidity"),
    hours: int = 24,
    db: AsyncSession = Depends(get_db)
):
    if metric in ("noise_resistance", "Rn"):
        table = "electrochemical_noise_data"
        col = "noise_resistance"
    elif metric in ("chloride_concentration", "Cl"):
        table = "microenvironment_data"
        col = "chloride_concentration"
    elif metric in ("temperature", "T"):
        table = "microenvironment_data"
        col = "temperature"
    elif metric in ("humidity", "RH"):
        table = "microenvironment_data"
        col = "humidity"
    elif metric in ("sulfur_dioxide", "SO2"):
        table = "microenvironment_data"
        col = "sulfur_dioxide"
    else:
        raise HTTPException(status_code=400, detail="Unsupported metric")

    query = text(f"""
        SELECT time_bucket('15 minutes', time) AS bucket,
               AVG({col}) AS avg_val,
               MIN({col}) AS min_val,
               MAX({col}) AS max_val
        FROM {table}
        WHERE artifact_id = :aid AND time > NOW() - INTERVAL ':hrs hours'
        GROUP BY bucket
        ORDER BY bucket
    """)
    result = await db.execute(query, {"aid": artifact_id, "hrs": hours})
    rows = result.fetchall()

    return {
        "metric": metric,
        "artifact_id": artifact_id,
        "points": [
            {
                "time": r[0].isoformat() if r[0] else None,
                "avg": float(r[1]) if r[1] else None,
                "min": float(r[2]) if r[2] else None,
                "max": float(r[3]) if r[3] else None
            }
            for r in rows
        ]
    }


@router.get("/artifacts/{artifact_id}/predictions", response_model=List[PredictionRead])
async def get_predictions(
    artifact_id: str,
    limit: int = 20,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(RustPrediction)
        .where(RustPrediction.artifact_id == artifact_id)
        .order_by(RustPrediction.prediction_time.desc())
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/sensors", response_model=List[SensorRead])
async def list_sensors(
    sensor_type: Optional[str] = None,
    artifact_id: Optional[str] = None,
    status: Optional[int] = None,
    limit: int = 200,
    db: AsyncSession = Depends(get_db)
):
    query = select(Sensor)
    conds = []
    if sensor_type:
        conds.append(Sensor.sensor_type == sensor_type)
    if artifact_id:
        conds.append(Sensor.artifact_id == artifact_id)
    if status is not None:
        conds.append(Sensor.status == status)
    if conds:
        query = query.where(and_(*conds))
    query = query.order_by(Sensor.sensor_id).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/alerts", response_model=List[AlertRead])
async def list_alerts(
    artifact_id: Optional[str] = None,
    severity: Optional[int] = None,
    resolved: Optional[bool] = None,
    acknowledged: Optional[bool] = None,
    hours: Optional[int] = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    query = select(Alert).order_by(Alert.alert_time.desc())
    conds = []
    if artifact_id:
        conds.append(Alert.artifact_id == artifact_id)
    if severity is not None:
        conds.append(Alert.severity == severity)
    if resolved is not None:
        conds.append(Alert.resolved == resolved)
    if acknowledged is not None:
        conds.append(Alert.acknowledged == acknowledged)
    if hours:
        conds.append(Alert.alert_time > datetime.utcnow() - timedelta(hours=hours))
    if conds:
        query = query.where(and_(*conds))
    query = query.limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/alerts/{alert_id}/acknowledge", response_model=AlertRead)
async def acknowledge_alert(
    alert_id: int,
    body: AlertAcknowledge,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Alert).where(Alert.alert_id == alert_id))
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(404, "Alert not found")
    alert.acknowledged = True
    alert.acknowledged_by = body.operator
    alert.acknowledged_at = datetime.utcnow()
    await db.commit()
    await db.refresh(alert)
    return alert


@router.post("/alerts/{alert_id}/resolve", response_model=AlertRead)
async def resolve_alert(
    alert_id: int,
    body: AlertResolve,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Alert).where(Alert.alert_id == alert_id))
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(404, "Alert not found")
    alert.resolved = True
    alert.resolved_at = datetime.utcnow()
    if body.notes:
        alert.message = (alert.message or "") + f"\n处置备注: {body.notes}"
    await db.commit()
    await db.refresh(alert)
    return alert


@router.post("/spray-tasks/optimize")
async def optimize_spray_plan(
    body: SprayTaskCreate,
    db: AsyncSession = Depends(get_db)
):
    optimizer = CFDSimplifiedSprayOptimizer()
    try:
        inhibitor = InhibitorType(body.inhibitor_type)
    except ValueError:
        raise HTTPException(400, "Invalid inhibitor type. Use BTA/AMT/MBO")

    opt_result = optimizer.optimize(
        artifact_id=body.artifact_id,
        target_zones=body.target_zones,
        artifact_size={"width": 0.5, "height": 0.6, "depth": 0.4},
        inhibitor_type=inhibitor,
        required_coverage=body.required_coverage
    )

    task = InhibitorSprayTask(
        artifact_id=body.artifact_id,
        alert_id=body.alert_id,
        inhibitor_type=body.inhibitor_type,
        concentration=10.0,
        total_volume=opt_result.total_volume_ml,
        target_zones=body.target_zones,
        spray_plan={
            "nozzle_positions": [
                {
                    "x": n.x, "y": n.y, "z": n.z,
                    "theta_x": n.theta_x, "theta_y": n.theta_y,
                    "spray_angle_deg": n.spray_angle_deg,
                    "pressure_bar": n.pressure_bar,
                    "dwell_time_s": n.dwell_time_s
                }
                for n in opt_result.nozzle_positions
            ],
            "zone_results": [
                {
                    "zone_id": z.zone_id,
                    "center": z.center,
                    "predicted_coverage": z.predicted_coverage,
                    "volume_ml": z.estimated_volume_ml,
                    "spray_time_s": z.spray_time_s,
                    "pass_count": z.pass_count
                }
                for z in opt_result.zone_results
            ],
            "spray_path": opt_result.spray_path,
            "cfd_summary": opt_result.cfd_simulation_summary
        },
        coverage_estimate=opt_result.estimated_coverage,
        status=0,
        scheduled_at=datetime.utcnow()
    )
    task_id = None
    try:
        db.add(task)
        await db.commit()
        await db.refresh(task)
        task_id = task.task_id
    except Exception as db_exc:
        logger.warning(
            f"Cannot persist spray task to DB (ok if no DB): {db_exc}. "
            f"Returning computed result without persistence."
        )
        try:
            await db.rollback()
        except Exception:
            pass
        task_id = f"memory-{body.artifact_id}-{int(datetime.utcnow().timestamp())}"

    return {
        "task_id": task_id,
        "artifact_id": body.artifact_id,
        "inhibitor_type": body.inhibitor_type,
        "total_volume_ml": opt_result.total_volume_ml,
        "total_time_s": opt_result.total_spray_time_s,
        "estimated_coverage": opt_result.estimated_coverage,
        "nozzle_positions": [
            {"x": n.x, "y": n.y, "z": n.z,
             "theta_x": n.theta_x, "theta_y": n.theta_y,
             "spray_angle": n.spray_angle_deg, "pressure": n.pressure_bar,
             "dwell": n.dwell_time_s}
            for n in opt_result.nozzle_positions
        ],
        "zone_results": [
            {
                "zone_id": z.zone_id,
                "center": z.center,
                "predicted_coverage": z.predicted_coverage,
                "volume_ml": z.estimated_volume_ml,
                "time_s": z.spray_time_s,
                "passes": z.pass_count
            }
            for z in opt_result.zone_results
        ],
        "cfd_summary": opt_result.cfd_simulation_summary,
        "spray_path": opt_result.spray_path,
        "persisted": task_id is not None and not str(task_id).startswith("memory-")
    }


@router.get("/spray-tasks", response_model=List[SprayTaskRead])
async def list_spray_tasks(
    artifact_id: Optional[str] = None,
    status: Optional[int] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db)
):
    query = select(InhibitorSprayTask).order_by(InhibitorSprayTask.created_at.desc())
    conds = []
    if artifact_id:
        conds.append(InhibitorSprayTask.artifact_id == artifact_id)
    if status is not None:
        conds.append(InhibitorSprayTask.status == status)
    if conds:
        query = query.where(and_(*conds))
    query = query.limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/spray-tasks/{task_id}/execute")
async def execute_spray_task(task_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(InhibitorSprayTask).where(InhibitorSprayTask.task_id == task_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "Task not found")
    if task.status != 0:
        raise HTTPException(400, "Task not in pending state")
    task.status = 1
    task.started_at = datetime.utcnow()
    await db.commit()
    await db.refresh(task)

    import asyncio

    async def simulate_execution():
        await asyncio.sleep(5)
        async with get_db_context() as db2:
            r = await db2.execute(
                select(InhibitorSprayTask).where(InhibitorSprayTask.task_id == task_id)
            )
            t2 = r.scalar_one_or_none()
            if t2 and t2.status == 1:
                t2.status = 2
                t2.completed_at = datetime.utcnow()
                t2.actual_volume = t2.total_volume
                t2.actual_coverage = t2.coverage_estimate
                await db2.commit()

    asyncio.create_task(simulate_execution())

    return {"message": "Spray task started", "task_id": task_id}


@router.get("/artifacts/{artifact_id}/risk-zones")
async def get_risk_zones(artifact_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(RustPrediction)
        .where(RustPrediction.artifact_id == artifact_id)
        .order_by(RustPrediction.prediction_time.desc())
        .limit(1)
    )
    pred = result.scalar_one_or_none()

    zones = pred.risk_zone if pred and pred.risk_zone else []
    if isinstance(zones, str):
        import json
        try:
            zones = json.loads(zones)
        except Exception:
            zones = []

    eruption_zones = []
    microscope_result = await db.execute(text("""
        SELECT has_rust_eruption, rust_detection, time
        FROM microscope_images
        WHERE artifact_id = :aid
        ORDER BY time DESC LIMIT 3
    """), {"aid": artifact_id})
    for row in microscope_result.fetchall():
        if row[0] and row[1]:
            import json
            det = row[1]
            if isinstance(det, str):
                try:
                    det = json.loads(det)
                except Exception:
                    continue
            for p in det.get("patches", []):
                bbox = p.get("bbox", {})
                eruption_zones.append({
                    "type": "eruption",
                    "patch_id": p.get("patch_id"),
                    "center": {
                        "x": bbox.get("x", 0.5) - 0.5,
                        "y": (1 - bbox.get("y", 0.5)) * 0.4 - 0.2,
                        "z": 0.05
                    },
                    "radius": 0.03 + p.get("severity", 0.5) * 0.05,
                    "severity": p.get("severity", 0.8),
                    "detected_at": row[2].isoformat() if row[2] else None
                })

    prediction_zones = []
    for z in zones:
        is_eruption = z.get("has_eruption", False)
        prediction_zones.append({
            "type": "eruption" if is_eruption else "risk",
            "zone_id": z.get("zone_id"),
            "center": z.get("center", {}),
            "radius": z.get("radius", 0.05),
            "severity": z.get("severity", 0.5),
            "from_prediction": True,
            "prediction_time": pred.prediction_time.isoformat() if pred else None,
            "eruption_probability": pred.eruption_probability if pred else None
        })

    return {
        "artifact_id": artifact_id,
        "prediction": {
            "prediction_time": pred.prediction_time.isoformat() if pred else None,
            "eruption_probability": pred.eruption_probability if pred else 0,
            "risk_level": pred.risk_level if pred else 1,
            "model_version": pred.model_version if pred else None
        } if pred else None,
        "risk_zones": prediction_zones,
        "eruption_zones": eruption_zones,
        "all_zones": prediction_zones + eruption_zones
    }


@router.post("/ingest/{sensor_type}")
async def ingest_data_direct(
    sensor_type: str,
    payload: Dict[str, Any]
):
    sensor_type = sensor_type.lower()
    if sensor_type not in ("electrochemical", "microenv", "microscope"):
        raise HTTPException(400, "Invalid sensor type")
    await data_processor.process_message(sensor_type, payload)
    return {"success": True, "message": f"{sensor_type} data ingested"}
