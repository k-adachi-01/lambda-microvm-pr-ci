### disposable microVM CI — `succeeded`

| field | value |
|---|---|
| jobId | `pr1-r39289676078-a1` |
| microvmId | `microvm-ae6dc977-db45-36a1-9d05-084ea105adb8` |
| PR | `#1` |
| head SHA | `52dde6c626f8010b8aef45f6388eb9f5720e4463` |
| run | `39289676078` attempt `1` |
| artifact sha256 | `6a97ecb706982092…` |

**timings (s):** package_upload_s=0.714 vm_launch_s=3.847 submit_s=0.727 job_s=3.787 fetch_s=1.099 terminate_s=3.493 total_s=13.742

| step | exit | ms |
|---|---|---|
| `python3 -m compileall src -q` | 0 | 1482 |
| `python3 -m unittest discover -s tests -v` | 0 | 714 |
