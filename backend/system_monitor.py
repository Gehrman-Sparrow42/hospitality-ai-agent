import os
import shutil
import time
from typing import Dict, Any

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

_boot_time = time.time()

def get_system_metrics() -> Dict[str, Any]:
    """Returns CPU, RAM, Swap, and Disk metrics."""
    metrics = {
        "cpu_percent": 0.0,
        "ram": {
            "used_mb": 0,
            "total_mb": 0,
            "percent": 0.0,
            "display": "0 / 0 MB"
        },
        "swap": {
            "used_mb": 0,
            "total_mb": 0,
            "percent": 0.0,
            "display": "0 / 0 MB"
        },
        "disk": {
            "used_gb": 0.0,
            "total_gb": 0.0,
            "percent": 0.0,
            "display": "0 / 0 GB"
        },
        "uptime": "0s"
    }

    # 1. Disk usage via standard library
    try:
        total, used, free = shutil.disk_usage("/")
        total_gb = round(total / (1024 ** 3), 1)
        used_gb = round(used / (1024 ** 3), 1)
        percent = round((used / total) * 100, 1) if total > 0 else 0.0
        metrics["disk"] = {
            "used_gb": used_gb,
            "total_gb": total_gb,
            "percent": percent,
            "display": f"{used_gb} / {total_gb} GB"
        }
    except Exception:
        pass

    # 2. psutil if available
    if HAS_PSUTIL:
        try:
            metrics["cpu_percent"] = round(psutil.cpu_percent(interval=None), 1)
            vm = psutil.virtual_memory()
            used_mb = int(vm.used / (1024 ** 2))
            total_mb = int(vm.total / (1024 ** 2))
            metrics["ram"] = {
                "used_mb": used_mb,
                "total_mb": total_mb,
                "percent": round(vm.percent, 1),
                "display": f"{used_mb} / {total_mb} MB"
            }
            
            sw = psutil.swap_memory()
            sw_used_mb = int(sw.used / (1024 ** 2))
            sw_total_mb = int(sw.total / (1024 ** 2))
            metrics["swap"] = {
                "used_mb": sw_used_mb,
                "total_mb": sw_total_mb,
                "percent": round(sw.percent, 1),
                "display": f"{sw_used_mb} / {sw_total_mb} MB"
            }
            
            uptime_seconds = int(time.time() - psutil.boot_time())
            hours, remainder = divmod(uptime_seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            metrics["uptime"] = f"{hours}s {minutes}d" if hours > 0 else f"{minutes}d"
            return metrics
        except Exception:
            pass

    # 3. Linux /proc fallback if psutil not present
    try:
        if os.path.exists("/proc/meminfo"):
            meminfo = {}
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    parts = line.split(":")
                    if len(parts) == 2:
                        key = parts[0].strip()
                        val = parts[1].strip().split()[0]
                        meminfo[key] = int(val)
            
            total_kb = meminfo.get("MemTotal", 0)
            avail_kb = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
            used_kb = total_kb - avail_kb
            if total_kb > 0:
                used_mb = int(used_kb / 1024)
                total_mb = int(total_kb / 1024)
                pct = round((used_kb / total_kb) * 100, 1)
                metrics["ram"] = {
                    "used_mb": used_mb,
                    "total_mb": total_mb,
                    "percent": pct,
                    "display": f"{used_mb} / {total_mb} MB"
                }

            sw_total_kb = meminfo.get("SwapTotal", 0)
            sw_free_kb = meminfo.get("SwapFree", 0)
            sw_used_kb = sw_total_kb - sw_free_kb
            if sw_total_kb > 0:
                sw_used_mb = int(sw_used_kb / 1024)
                sw_total_mb = int(sw_total_kb / 1024)
                sw_pct = round((sw_used_kb / sw_total_kb) * 100, 1)
                metrics["swap"] = {
                    "used_mb": sw_used_mb,
                    "total_mb": sw_total_mb,
                    "percent": sw_pct,
                    "display": f"{sw_used_mb} / {sw_total_mb} MB"
                }
    except Exception:
        pass

    # CPU load average fallback
    try:
        if hasattr(os, "getloadavg"):
            load1, _, _ = os.getloadavg()
            cpu_count = os.cpu_count() or 1
            metrics["cpu_percent"] = round(min(100.0, (load1 / cpu_count) * 100), 1)
    except Exception:
        pass

    uptime_sec = int(time.time() - _boot_time)
    hours, remainder = divmod(uptime_sec, 3600)
    minutes, _ = divmod(remainder, 60)
    metrics["uptime"] = f"{hours}s {minutes}d" if hours > 0 else f"{minutes}d"

    return metrics
