### disposable microVM CI — `succeeded`

| field | value |
|---|---|
| jobId | `pr6-r41304382597-a1` |
| microvmId | `microvm-221895a7-c9d6-3fd3-8951-223a9efc71fa` |
| PR | `#6` |
| head SHA | `7f75327cd8ae33e39747a6b6b390c658d201b86b` |
| run | `41304382597` attempt `1` |
| artifact sha256 | `03d58ee33125a038…` |
| result bundle | verified |
| VM termination | verified |

**timings (s):** package_upload_s=0.985 vm_launch_s=3.974 submit_s=0.893 job_s=7.46 fetch_s=1.401 terminate_s=3.577 total_s=18.35

| step | exit | ms |
|---|---|---|
| `python3 -m compileall src -q` | 0 | 2475 |
| `python3 -m unittest discover -s tests -v` | 0 | 916 |
