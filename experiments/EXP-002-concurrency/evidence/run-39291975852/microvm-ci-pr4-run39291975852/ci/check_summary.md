### disposable microVM CI — `succeeded`

| field | value |
|---|---|
| jobId | `pr4-r39291975852-a1` |
| microvmId | `microvm-8595fd26-a1ed-3acd-891e-b79c5e0951b5` |
| PR | `#4` |
| head SHA | `6ed0763c6f9123951e2c113eb9b6126a993f1d1b` |
| run | `39291975852` attempt `1` |
| artifact sha256 | `a70a14a6501f1962…` |

**timings (s):** package_upload_s=0.827 vm_launch_s=4.066 submit_s=0.739 job_s=3.83 fetch_s=1.371 terminate_s=3.584 total_s=14.485

| step | exit | ms |
|---|---|---|
| `python3 -m compileall src -q` | 0 | 116 |
| `python3 -m unittest discover -s tests -v` | 0 | 163 |
