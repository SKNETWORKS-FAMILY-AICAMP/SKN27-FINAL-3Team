# Data Loaders

This folder contains batch-style scripts that load source data into Road PostGIS.

V1 source data:

1. South Korea OSM PBF
2. Road guide signs
3. Traffic signals
4. Crosswalks
5. Protection zones

The intended flow is:

```text
download/source API
-> raw snapshot
-> staging table
-> validation
-> production table swap
```

These scripts are scaffolds. They intentionally avoid changing production tables
until validation logic is implemented.
