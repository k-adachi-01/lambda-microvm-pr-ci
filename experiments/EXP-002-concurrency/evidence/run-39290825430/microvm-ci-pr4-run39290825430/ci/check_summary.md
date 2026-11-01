### disposable microVM CI — `succeeded`

| field | value |
|---|---|
| jobId | `pr4-r39290825430-a1` |
| microvmId | `microvm-d6d2d64a-943e-3d01-b10e-5ff514c0d275` |
| PR | `#4` |
| head SHA | `6ed0763c6f9123951e2c113eb9b6126a993f1d1b` |
| run | `39290825430` attempt `1` |
| artifact sha256 | `a70a14a6501f1962…` |

**timings (s):** package_upload_s=0.964 vm_launch_s=4.168 submit_s=0.855 job_s=0.497 fetch_s=1.579 terminate_s=3.647 total_s=11.786

| step | exit | ms |
|---|---|---|
| `python3 -m compileall src -q` | 0 | 115 |
| `python3 -m unittest discover -s tests -v` | 0 | 163 |
