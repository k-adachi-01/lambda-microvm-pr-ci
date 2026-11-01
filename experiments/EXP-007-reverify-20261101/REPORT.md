# EXP-007: 修正後の再検証（fail-closed 化・インフラ再構築・掃討の実動作）

## 目的

2026-10-20 レビューの修正必須 3 件（終了判定・S3 結果検証・workflow の値埋め込み）と sweeper の実動作を、再構築した PoC Sandbox 環境で検証する。あわせて、検証後に K-344 の資源を残さないための撤収手順を確立する。

## 予測

- pass/fail の PR で Check が正しく往復し、summary に `resultBundle.verified=true` と `terminationVerified=true` が入る `[推論]`
- OIDC 拒否・timeout・sha 偽装の各経路で Check=fail、VM は TERMINATED `[推論]`
- sweeper は `startedAt` を基準に古い VM を終了し、終了後の `aliveVms` は 0 になる `[推論]`
- 結果 bundle 不在・終了未確認は exit 2 になり、成功扱いにならない（unit test で確認） `[推論]`

## 環境

- 日時: 2026-11-01（JST）
- AWS: PoC Sandbox `155936382172` / `ap-northeast-1`
- 実験 ID: `20261101-k344-reverify-001`、expires-at `2026-11-02`
- repo: `k-adachi-01/lambda-microvm-pr-ci`、検証時の main `94b0179`（workflow 修正）
- CI image: `arn:aws:lambda:ap-northeast-1:155936382172:microvm-image:k344-ci` version `2.0`（2026-11-01T20:40:24+09:00 更新）
- runner: GitHub-hosted `ubuntu-latest`、orchestrator は OIDC role `k344-prci-github-actions-role`
- ローカル: macOS arm64、Python 3.14（uv）、boto3 1.43.114

## 手順

1. 人の SSO（`aws-poc-sandbox`）で `infra/deploy.sh` を実行し、bucket / build・execution・OIDC role を再作成
2. `scripts/lease -- scripts/build-ci-image.sh` で image version 2.0 を作成
3. pass PR #6（`verify/pass-20261101`）と fail PR #7（`verify/fail-20261101`）を作成
4. `workflow_dispatch` で timeout（PR #5, `job_timeout_seconds=10`）、OIDC 拒否（build role 指定）、fork ゲート（`simulate_fork_gate=true`）、sha 偽装（`tamper_sha=true`）を注入
5. sweeper を workflow_dispatch で実行し、さらに RUNNING の VM を手動起動して `cleanup_stale.py --max-age-minutes 0` で終了させる
6. 各 run の artifact と Check output を保存し、VM/S3 の状態を API で確認
7. 終了後、`scripts/teardown_k344.py --apply` と `scripts/verify_clean.py` で撤収（結果は同 evidence 配下）

## 結果（実測）

### E2E と失敗注入

| ケース | run | 結果 | microvmId | VM 部分の主な値 |
|---|---|---|---|---|
| pass（PR #6） | `41304382597` | job success / Check `run` pass / title `microvm-ci: succeeded` | `microvm-221895a7-c9d6-3fd3-8951-223a9efc71fa` | total 18.35s, launch 3.974s, job 7.46s, terminate 3.577s |
| fail（PR #7） | `41304479817` | job failure / Check `run` fail / title `microvm-ci: failed` | `microvm-6a939cba-ad26-3ca1-a27d-9ea72112249d` | total 17.254s, job 7.148s, step exit 1 |
| timeout（PR #5, 10s） | `41304553365` | job failure / step `timedOut=true` | `microvm-a1bd5d47-b570-3bd6-a3ff-a7dcb7968eeb` | job_s 11.073s |
| OIDC 拒否 | `41304625125` | `Configure AWS credentials` で failure / Check title `microvm-ci: no-status` | なし（VM 未起動） | – |
| fork ゲート | `41304842135` | job success / neutral check `124843053300` / title `not run — fork requires label` | なし | early exit |
| sha 偽装 | `41304876697` | job failure / `artifact sha256 mismatch` | `microvm-8d7e04b6-1015-3e58-8d1b-bbd6aba311e0` | job_s 0.336s |

pass/fail/timeout/tamper の全 run で `resultBundle.verified=true`、`terminationVerified=true`、`verificationStatus=ok`。Check summary には result bundle / VM termination の行が入る（`evidence/run-*/.../ci/check_summary.md`）。

### 掃討（sweeper）の実動作

- 手動起動した RUNNING VM `microvm-10edcd33-87c9-3185-9793-b450cdaa8504` に対し `cleanup_stale.py --max-age-minutes 0` を実行 → `action=terminated`, `stateAfter=TERMINATED`, `aliveVms=0`, exit 0（`evidence/sweeper-local.json`）
- workflow_dispatch の sweeper run `41304921774` は success、`aliveVms=0`, `s3Deleted=0`（`evidence/sweeper-41304921774.log`）
- 検証中に **sweeper の既存バグ**を発見した: `list-microvms` の項目は `createdAt` ではなく `startedAt` を返すため、旧実装では全 VM が age 不明（None）となり、**stale VM を一度も終了できなかった**。`startedAt` を読むよう修正し、上記の実動作で確認した。

### 回帰テスト

`uv run python -m unittest discover -s ci/tests -v` で 24 tests OK。

- `wait_terminated`: TERMINATED / ResourceNotFoundException は verified、AccessDenied・その他例外・timeout は unverified
- `verify_result_bundle`: 存在・サイズ>0 のみ verified、不在・0 バイトは unverified
- `determine_exit_code`: 結果 or 終了が未確認なら 2（成功にしない）
- workflow 静的検査: ラベル JSON と dispatch 入力が `run:` に直接埋め込まれていないこと、fork tarball が head repo を使うこと
- `cleanup_stale.parse_time`: `startedAt` の datetime/ISO 文字列/epoch を正規化できること

### インフラ再構築で見つけた追加の不具合

- `scripts/build-ci-image.sh` の待機ループが image state `UPDATED` を受け付けず、更新成功後も 30 分待ち続けた。`UPDATED` を成功状態に追加した。

### 撤収と残存確認

- `scripts/teardown_k344.py --apply`: MicroVM image、S3 bucket、IAM role 3 件、log group を削除（`evidence/teardown/teardown.json`）
- 旧比較用 CodeBuild project `k344-prci-compare`（experiment_id `20261020-k344-001`）も削除（`evidence/teardown/codebuild-cleanup.txt`）
- `scripts/delstack_check.sh`: delstack v2.12.3 で CloudFormation を確認。残るのは保全対象の `CDKToolkit` のみで、K-344 スタックは 0（`evidence/teardown/delstack.log`）
- `scripts/verify_clean.py`: `clean: true`。IAM role / S3 bucket / MicroVM image / active VM / log group / CodeBuild / ECR / k344 タグ付き資源はすべて空（`evidence/teardown/verify-clean.json`）
- TERMINATED の VM 履歴 5 件は API 上に残るが、`activeMicrovmVms` は空。Lambda MicroVMs には VM 削除 API がなく、これは履歴であって稼働資源ではない `[仕様: aws lambda-microvms help]`

## 解釈

- 予測どおり、pass/fail の往復と失敗注入の全経路で Check が正しく否定結果を返し、VM は TERMINATED になった。
- レビュー指摘 3 件はコード上で fail-closed になり、unit test と E2E の両方で確認できた。特に Check summary に verification 行を出したことで、「guest は succeeded だが結果が未確認」を目視できる。
- sweeper の `createdAt` バグは、EXP-006 の時点で stale VM が無かったため露見していなかった。今回の能動的な RUNNING VM テストで初めて再現し、修正後に終了まで確認した。
- `workflow_dispatch` の Check は dispatch した ref（main）に付くため、PR head の Check を更新するのは `pull_request_target` 経路だけである。これは仕様どおりだが、dispatch で PR の Check を上書きしたい場合は別途 check-run を指定する必要がある。

## 限界と残る疑問

- 実 fork PR の E2E は引き続き未確認（単一アカウントで自 repo fork を作れない）。tarball URL を head repo に変更したが、実イベントでは未検証 `[未確認]`。
- 結果 bundle 不在・終了 AccessDenied の E2E 注入は行っていない。unit test で exit 2 を確認したのみ `[未確認: E2E]`。
- 並行度・quota の再測は行っていない（小サンプル） `[未確認]`。
- 検証後の撤収結果は `evidence/teardown/` と `evidence/verify-clean.json` を参照。
