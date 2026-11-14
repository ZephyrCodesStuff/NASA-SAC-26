import os

# Tests must not read or write the real result cache.
os.environ.setdefault("PARCEL_API_DISK_CACHE", "0")
