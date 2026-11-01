# EXP-004: 失敗注入 — OIDC 拒否 / job timeout / runner cancel / S3 不整合 / RunMicrovm 過負荷

## 目的

各失敗経路で (a) Check に正しい否定結果が返るか (b) VM と S3 一時資源が回収されるか、を実測する。

## 予測

- OIDC 拒否: creds 取得時点で失敗し VM は起きない。Check = fail
- job timeout: agent が step を kill し failed、VM terminate
- runner cancel: SIGTERM で finally が走り terminate
- S3 不整合: sha256 mismatch で agent が artifact 拒否、failed
- RunMicrovm 過負荷: リトライで吸収 or 明確な失敗 + terminate

## 手順

- `workflow_dispatch` で注入: `tamper_sha=true`（sha 偽装）/ `job_timeout_seconds=10`（遅いテスト）/ `role_arn_override=<build-role>`（AssumeRole 不可 role）
- `gh run cancel` で runner cancel（実行中の VM あり状態で）
- `scripts/lease` 下で 5 並列 RunMicrovm burst（botocore retry 無効で生応答を観測）

## 結果 [実測]

| 注入 | run / 手段 | 観測 |
|---|---|---|
| OIDC 拒否（build-role を指定） | `39291217778` | `Configure AWS credentials` step で失敗。VM 起動せず。Check=fail（`microvm-ci: ` title 空の check output）[実測] |
| job timeout 10s（20s テスト） | `39291213262` | `job_s=10.68s` で step `exitCode=None,timedOut` → jobStatus=failed → Check `microvm-ci: failed`。VM `microvm-e3a713e8` TERMINATED [実測] |
| runner cancel（VM RUNNING 中） | `39291034787` を `gh run cancel` | `microvm-4cc6816c` は RUNNING から TERMINATED に遷移。SIGTERM→finally の経路で回収 [実測] |
| S3 不整合（sha 偽装） | `39291207820` | `job_s=0.351s` で即 reject → jobStatus=failed → Check `microvm-ci: failed`。VM `microvm-dc2e0f80` TERMINATED [実測] |
| RunMicrovm 過負荷 | lease 下 5 並列 burst | 3 成功 / 2 が `ServiceQuotaExceededException` ×6 リトライ全失敗。429 系ではなく**同時メモリ 8GiB クォータ超過**が支配的。`ci_job.py` の retryable codes に追加済（`evidence/throttle-burst.json`）[実測] |

## 解釈

- 失敗は全て Check に `failed`（または cancelled）として返る。runner 側では「VM が起きる前の失敗（OIDC）」と「VM 内の失敗（sha/timeout）」が異なる step で観測できる [実測]
- runner cancel で VM が残らないのは orchestrator の SIGTERM handler + finally のおかげ。これが無いと `maximumDurationInSeconds`（900s）まで VM が走り続ける [推論]
- throttle の実像は `TooManyRequests` ではなく `ServiceQuotaExceededException`。同時メモリ枠（8GiB / 2048MiB-image で ~4台）が先に効く。CI 用途では「瞬時バーストを短いリトライで吸収→駄目なら fail」が現実解 [実測]

## 限界と残る疑問

- `job timeout` は step 単位の timeout で、VM 全体のハング（agent が応答しない）は `maximumDurationInSeconds` 頼り + orchestrator 側 poll timeout（job_timeout+120s）。agent ハング時の run 側 timeout パスは未検証 [未確認]
- `ServiceQuotaExceededException` のリトライは bounded（6回/最大 ~20s+jit）。高負荷時の継続待ち（キューイング）は未実装 [実装]
- sweeper は `image-arn` 絞り込み済みだが、「20 分を超えた VM」を kill するだけで、run との対応付け（どの run が VM を残したか）は行わない [実装]
