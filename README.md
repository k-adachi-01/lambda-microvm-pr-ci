# lambda-microvm-pr-ci (K-344)

GitHub PR ごとに Lambda MicroVM 使い捨て CI を起動し、結果を Checks に返す検証リポジトリ。

Linear: [K-344](https://linear.app/k-adachi-01/issue/K-344) / 前身: [K-333](https://linear.app/k-adachi-01/issue/K-333)（固定 Image + S3 presigned GET/PUT + SHA-256 + テスト + 終了 PoC、12.9–15.3s/ジョブ実測）

## アーキテクチャ

```
PR event (pull_request_target)
  → GitHub-hosted runner (trusted control plane ONLY)
      → tarball download (inert bytes; never executed here)
      → OIDC → k344-prci-github-actions-role (least privilege)
      → ci_job.py: S3 presigned GET/PUT → RunMicrovm(k344-ci, creds-free)
          → ci_agent.py: sha256 verify → extract → run steps → result bundle
      → terminate → GitHub Check run (job conclusion + output update)
```

信頼境界の要点:

- `pull_request_target` で workflow 定義は常に base ブランチのもの。PR が `.github/workflows/` を改変しても実行されない
- Runner は PR コードを checkout/実行しない。tarball をバイト列として取得し、VM 内でのみ実行される
- 実行ステップは workflow（base ブランチ）に固定。ゲスト側から手順を変えられない
- MicroVM は AWS 資格情報なし（execution role 未指定）。S3 とのやり取りは job 単位の presigned URL のみ
- fork PR は `microvm-ci-ok` ラベル必須。未ラベルは neutral check でスキップ
- 孤立 VM 対策: `maximumDurationInSeconds` 上限 + finally/SIGTERM terminate + `microvm-ci-sweeper` 定期掃討 + S3 lifecycle

## 構成

| パス | 内容 |
|---|---|
| `src/`, `tests/` | 被験プロジェクト（PR が変更する対象。stdlib unittest のみ） |
| `ci/image/` | 固定 CI イメージ（`ci_agent.py` が HTTP /job を受ける） |
| `ci/orchestrator/ci_job.py` | オーケストレータ（S3 + SHA-256 + RunMicrovm + 回収 + terminate） |
| `infra/` | OIDC CI role / build・execution role / artifact bucket の IaC（AWS CLI + JSON policy） |
| `.github/workflows/microvm-ci.yml` | PR 発火 → MicroVM CI → Checks |
| `.github/workflows/gha-baseline.yml` | 比較用: 同一テストを GitHub-hosted runner で直接実行 |
| `.github/workflows/microvm-ci-sweeper.yml` | 孤立 VM / 古い S3 オブジェクト掃討 |
| `buildspec.yml` | 比較用: 同一テストの CodeBuild 定義 |
| `scripts/` | lease、イメージ build、stale 掃討 |
| `experiments/EXP-*/` | 実験記録（REPORT.md + evidence/） |

## セットアップ（人の権限で1回）

```bash
# OIDC trust/role/bucket（人の SSO。agent-lease には iam:*OIDC* が無い）
/Users/adachi/agent-skills/aws-sandbox-run/scripts/aws-sandbox-run \
  --experiment-id 20261020-k344-001 --expires-at 2026-10-22 -- infra/deploy.sh

# CI イメージ build（agent lease で可）
scripts/lease -- scripts/build-ci-image.sh

# repo variables（infra/outputs.env の値を設定）
gh variable set MICROVM_CI_ROLE_ARN -b"$(grep CI_ROLE_ARN infra/outputs.env | cut -d= -f2)"
gh variable set ARTIFACT_BUCKET   -b"$(grep ARTIFACT_BUCKET infra/outputs.env | cut -d= -f2)"
gh variable set CI_IMAGE_ARN      -b"arn:aws:lambda:ap-northeast-1:$(grep ACCOUNT infra/outputs.env | cut -d= -f2):microvm-image:k344-ci"
```

## 実験の位置づけ

experiments/EXP-*/REPORT.md に実測を記録する（AGENTS.md の証拠区分 `[仕様]/[実測]/[推論]/[未確認]` に従う）。
