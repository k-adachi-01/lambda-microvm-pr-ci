### disposable microVM CI — `failed`

| field | value |
|---|---|
| jobId | `pr7-r41304479817-a1` |
| microvmId | `microvm-6a939cba-ad26-3ca1-a27d-9ea72112249d` |
| PR | `#7` |
| head SHA | `45fa32b264b72800c9bf0dc2209344365d9dc34c` |
| run | `41304479817` attempt `1` |
| artifact sha256 | `0154888ff1a75758…` |
| result bundle | verified |
| VM termination | verified |

**timings (s):** package_upload_s=0.792 vm_launch_s=3.878 submit_s=0.758 job_s=7.148 fetch_s=1.108 terminate_s=3.487 total_s=17.254

| step | exit | ms |
|---|---|---|
| `python3 -m compileall src -q` | 0 | 1881 |
| `python3 -m unittest discover -s tests -v` | 1 | 664 |
