### disposable microVM CI — `failed`

| field | value |
|---|---|
| jobId | `pr5-r41304553365-a1` |
| microvmId | `microvm-a1bd5d47-b570-3bd6-a3ff-a7dcb7968eeb` |
| PR | `#5` |
| head SHA | `c8ffbdc28070d8cf5b253da8fa4d89d118689ccc` |
| run | `41304553365` attempt `1` |
| artifact sha256 | `703a777d084df96a…` |
| result bundle | verified |
| VM termination | verified |

**timings (s):** package_upload_s=0.9 vm_launch_s=4.208 submit_s=0.883 job_s=11.073 fetch_s=1.6 terminate_s=3.645 total_s=22.409

| step | exit | ms |
|---|---|---|
| `python3 -m compileall src -q` | 0 | 1313 |
| `python3 -m unittest discover -s tests -v` | None | 8686 |
