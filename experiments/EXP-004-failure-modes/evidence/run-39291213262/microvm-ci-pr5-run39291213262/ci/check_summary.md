### disposable microVM CI — `failed`

| field | value |
|---|---|
| jobId | `pr5-r39291213262-a1` |
| microvmId | `microvm-e3a713e8-0c5e-368d-8ded-77fa990815da` |
| PR | `#5` |
| head SHA | `c8ffbdc28070d8cf5b253da8fa4d89d118689ccc` |
| run | `39291213262` attempt `1` |
| artifact sha256 | `703a777d084df96a…` |

**timings (s):** package_upload_s=0.887 vm_launch_s=4.029 submit_s=0.714 job_s=10.68 fetch_s=1.339 terminate_s=3.571 total_s=21.282

| step | exit | ms |
|---|---|---|
| `python3 -m compileall src -q` | 0 | 114 |
| `python3 -m unittest discover -s tests -v` | None | 9886 |
