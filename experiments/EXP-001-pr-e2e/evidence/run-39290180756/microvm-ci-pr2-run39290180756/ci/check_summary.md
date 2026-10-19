### disposable microVM CI — `failed`

| field | value |
|---|---|
| jobId | `pr2-r39290180756-a1` |
| microvmId | `microvm-a760258e-c51e-3962-8166-2606086a93b7` |
| PR | `#2` |
| head SHA | `ae3c278e4d35180c03e8ccbd8a3ebfbd09629684` |
| run | `39290180756` attempt `1` |
| artifact sha256 | `93c3a42c23d77695…` |

**timings (s):** package_upload_s=0.815 vm_launch_s=3.992 submit_s=0.819 job_s=3.78 fetch_s=1.35 terminate_s=3.549 total_s=14.395

| step | exit | ms |
|---|---|---|
| `python3 -m compileall src -q` | 0 | 993 |
| `python3 -m unittest discover -s tests -v` | 1 | 664 |
