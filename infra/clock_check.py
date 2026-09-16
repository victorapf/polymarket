"""
CAPA 2.3 - Sincronizacion de reloj.

La sincronizacion de fondo debe hacerse a nivel de SO (chrony / systemd-timesyncd,
ver docker-compose.yml y el Dockerfile), no en Python. Lo que si vive en la
aplicacion es una verificacion de sanidad al arrancar: comparar el reloj local
contra un servidor NTP publico y negarse a firmar ordenes EIP-712 si la deriva
excede el margen tolerado, en vez de descubrirlo por un rechazo `Timestamp Invalid`.
"""
from __future__ import annotations

import ntplib

MAX_DRIFT_S = 0.5


class ClockDriftError(RuntimeError):
    pass


def check_clock_drift(ntp_server: str = "pool.ntp.org", max_drift_s: float = MAX_DRIFT_S) -> float:
    client = ntplib.NTPClient()
    response = client.request(ntp_server, version=3, timeout=3)
    drift = response.offset
    if abs(drift) > max_drift_s:
        raise ClockDriftError(
            f"Deriva de reloj de {drift:.3f}s excede el maximo tolerado ({max_drift_s}s). "
            "Verificar chrony/systemd-timesyncd antes de operar."
        )
    return drift
