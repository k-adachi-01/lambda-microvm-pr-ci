### disposable microVM CI — `succeeded`

| field | value |
|---|---|
| jobId | `pr1-r39290061667-a1` |
| microvmId | `microvm-1d81bff0-2e09-368e-9688-a59f599498f3` |
| PR | `#1` |
| head SHA | `e2b3c52b1aeceeda3f9acdbf6d94d3b139599fc0` |
| run | `39290061667` attempt `1` |
| artifact sha256 | `9d10454eda1c0611…` |

**timings (s):** package_upload_s=0.674 vm_launch_s=3.84 submit_s=0.733 job_s=3.838 fetch_s=1.02 terminate_s=3.5 total_s=13.694

| step | exit | ms |
|---|---|---|
| `python3 -m compileall src -q` | 0 | 1435 |
| `python3 -m unittest discover -s tests -v` | 0 | 664 |
