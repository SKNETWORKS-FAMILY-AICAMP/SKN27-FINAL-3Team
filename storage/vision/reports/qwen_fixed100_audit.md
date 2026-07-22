# Qwen fixed-100 audit

| category | rows | JSON valid | target correct | accuracy | uncertain | parse errors | review |
|---|---:|---:|---:|---:|---:|---:|---:|
| car_vs_car | 100 | 91 | 63 | 63.0% | 37 | 9 | 37 |
| car_vs_pedestrian | 100 | 90 | 12 | 12.0% | 41 | 10 | 41 |
| car_vs_motorcycle | 100 | 84 | 0 | 0.0% | 40 | 16 | 40 |
| car_vs_bicycle | 100 | 86 | 2 | 2.0% | 49 | 14 | 49 |

- fixed results: 400/400
- JSON valid: 351/400
- target correct: 77/400 (19.2%)
- uncertain: 167/400
- parse errors: 49/400
- requires review: 167/400
