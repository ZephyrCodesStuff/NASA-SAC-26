"""
Configuration module for Field Ingestion & Input Parser API.
Handles server host/port and NASA/Earth observation dataset parameters.
"""

import os
from typing import List
from dotenv import load_dotenv

# Load .env file from project root or current folder
load_dotenv()

# Server settings
API_HOST: str = os.getenv("NASLOP_HOST", "0.0.0.0")
API_PORT: int = int(os.getenv("NASLOP_PORT", "8000"))
DEBUG: bool = os.getenv("NASLOP_DEBUG", "True").lower() in ("true", "1", "yes")

# Local data stores
SQLITE_PATH: str = os.getenv("NASLOP_SQLITE_PATH", "data/nasa_farming.db")
DUCKDB_PATH: str = os.getenv("NASLOP_DUCKDB_PATH", "data/nasa_farming.duckdb")

# NASA POWER agro-meteorological parameters
NASA_AGRO_PARAMETERS: List[str] = [
    "T2M",               # 2-meter air temperature (°C)
    "T2M_MAX",           # Daily max air temperature (°C)
    "T2M_MIN",           # Daily min air temperature (°C)
    "PRECTOTCORR",       # Daily corrected precipitation (mm/day)
    "ALLSKY_SFC_SW_DWN", # All Sky Insolation incident on horizontal surface (MJ/m^2/day)
    "RH2M",              # 2-meter relative humidity (%)
    "WS2M",              # 2-meter wind speed (m/s)
    "T2MDEW",            # Dew point temperature (°C)
    "PS"                 # Surface pressure (kPa)
]
