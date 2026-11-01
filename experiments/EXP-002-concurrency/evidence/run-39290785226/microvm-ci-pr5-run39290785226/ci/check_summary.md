### disposable microVM CI — `succeeded`

| field | value |
|---|---|
| jobId | `pr5-r39290785226-a1` |
| microvmId | `microvm-b8eaf589-8abb-3972-9108-36a44255745d` |
| PR | `#5` |
| head SHA | `c8ffbdc28070d8cf5b253da8fa4d89d118689ccc` |
| run | `39290785226` attempt `1` |
| artifact sha256 | `703a777d084df96a…` |

**timings (s):** package_upload_s=0.838 vm_launch_s=4.064 submit_s=0.874 job_s=24.528 fetch_s=1.405 terminate_s=3.587 total_s=35.386

| step | exit | ms |
|---|---|---|
| `python3 -m compileall src -q` | 0 | 1458 |
| `python3 -m unittest discover -s tests -v` | 0 | 20490 |
