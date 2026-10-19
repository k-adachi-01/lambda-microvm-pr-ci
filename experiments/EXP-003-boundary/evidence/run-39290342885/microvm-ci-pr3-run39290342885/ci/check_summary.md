### disposable microVM CI — `succeeded`

| field | value |
|---|---|
| jobId | `pr3-r39290342885-a1` |
| microvmId | `microvm-ddf8df50-3f7b-3379-8028-c55dfa2c6c36` |
| PR | `#3` |
| head SHA | `a3ada934ff98b7e98aff28c63e653487c005d6b7` |
| run | `39290342885` attempt `1` |
| artifact sha256 | `7bb14b6c8210da92…` |

**timings (s):** package_upload_s=0.853 vm_launch_s=4.064 submit_s=0.715 job_s=3.837 fetch_s=1.336 terminate_s=3.566 total_s=14.431

| step | exit | ms |
|---|---|---|
| `python3 -m compileall src -q` | 0 | 1050 |
| `python3 -m unittest discover -s tests -v` | 0 | 1015 |
