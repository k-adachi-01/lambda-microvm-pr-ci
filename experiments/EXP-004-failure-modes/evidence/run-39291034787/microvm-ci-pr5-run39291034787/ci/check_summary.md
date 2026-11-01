### disposable microVM CI — `succeeded`

| field | value |
|---|---|
| jobId | `pr5-r39291034787-a1` |
| microvmId | `microvm-4cc6816c-d004-354d-b94e-dd9faf146290` |
| PR | `#5` |
| head SHA | `c8ffbdc28070d8cf5b253da8fa4d89d118689ccc` |
| run | `39291034787` attempt `1` |
| artifact sha256 | `703a777d084df96a…` |

**timings (s):** package_upload_s=0.83 vm_launch_s=4.028 submit_s=0.734 job_s=20.932 fetch_s=1.379 terminate_s=3.567 total_s=31.534

| step | exit | ms |
|---|---|---|
| `python3 -m compileall src -q` | 0 | 114 |
| `python3 -m unittest discover -s tests -v` | 0 | 20190 |
