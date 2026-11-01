### disposable microVM CI — `succeeded`

| field | value |
|---|---|
| jobId | `pr4-r39291987587-a1` |
| microvmId | `microvm-74551c07-ff49-316c-9a5f-3a749bd932bd` |
| PR | `#4` |
| head SHA | `6ed0763c6f9123951e2c113eb9b6126a993f1d1b` |
| run | `39291987587` attempt `1` |
| artifact sha256 | `a70a14a6501f1962…` |

**timings (s):** package_upload_s=0.968 vm_launch_s=4.117 submit_s=0.834 job_s=0.489 fetch_s=1.592 terminate_s=3.652 total_s=11.744

| step | exit | ms |
|---|---|---|
| `python3 -m compileall src -q` | 0 | 114 |
| `python3 -m unittest discover -s tests -v` | 0 | 163 |
