# EXP-001: PR 発火 → MicroVM CI → Checks の E2E（成功/失敗 + OIDC trust 最小化）

## 目的

- 単一 PR で「テスト成功 → Check pass」「テスト失敗 → Check fail」が信頼できる形で往復するか
- OIDC trust の初期条件（bootstrap の広すぎない sub）を実測クレームに基づき最小化できるか

## 予測

- `pull_request_target` で発火し base ブランチの workflow が走り、job 成否がそのまま Check になる
- `sub` は不変ID形式 `repo:<owner>@<owner_id>/<repo>@<repo_id>:<context>` になり、context は `pull_request`（pull_request_target でも `pull_request` と推測）[推論]

## 環境

- GitHub repo `k-adachi-01/lambda-microvm-pr-ci`（2026-10-19 作成→不変sub対象 [仕様]、途中 visibility public 化 ※hosted runner課金障害のため）
- AWS PoC Sandbox ap-northeast-1、image `arn:aws:lambda:ap-northeast-1:155936382172:microvm-image:k344-ci`（minMemory 2048MiB）[実測]
- OIDC provider `token.actions.githubusercontent.com` はアカウント既存（K-333 由来）[実測]

## 手順

1. `infra/deploy.sh`（人の SSO / `aws-sandbox-run`）で bucket + 3 role を作成。`ci_trust.json` は phase-1 = `repository_id`/`repository_owner_id` 固定 + `sub` repo スコープワイルドカード
2. `scripts/lease -- scripts/build-ci-image.sh` で `k344-ci` build
3. PR#1（pass）・PR#2（fail）を作成し run/Check/VM/S3 を観測
4. run の ID token payload を証拠採取後、`sub` を実測2値に絞って trust 更新 → 再実行で確認

## 結果 [実測]

| 項目 | 観測 |
|---|---|
| PR#1 pass | run `39289676078` 33s → job success → Check `run` = pass。VM `microvm-ae6dc977` → TERMINATED。result bundle S3 着地（`ci/pr-1/…/result.bundle.tar.gz`） |
| PR#2 fail | run `39290180756` 29s → Check `run` = fail（`microvm-ci: failed` の check output 更新） |
| Check 出力 | check-run `output.title`=`microvm-ci: succeeded`、summary に microvmId/timings/steps が入る（`evidence/run-*/microvm-ci-*/ci/check_summary.md`） |
| VM job 部分の時間 | `total_s` 13.7s / 起動 3.85s / job 3.79s / terminate 3.49s（K-333 の 12.9–15.3s と同水準）[実測] |
| OIDC claims | `evidence/oidc-claims.json`：`sub=repo:k-adachi-01@209649144/lambda-microvm-pr-ci@1425896105:pull_request`、`event_name=pull_request_target`、`ref=refs/heads/main`、`job_workflow_ref=…@refs/heads/main` |
| trust 最小化後 | `ci_trust.json` を `sub ∈ {…:pull_request, …:ref:refs/heads/main}` に更新 → run `39290061667` も成功（pull_request_target context での認証は継続）[実測] |
| schedule/dispatch 系 | sweeper run `39292121974` が成功（`:ref:refs/heads/main` sub で認証）[実測] |

## 解釈

- 予測通り PR→Checks の pass/fail 往復が成立。workflow conclusion → Check の伝播と check-run output 更新（microvmId 等の証拠メタ）まで確認 [実測]
- `pull_request_target` の `sub` context は `pull_request`。`event_name` claim で `pull_request_target` 本体は識別できる [実測]
- AWS 側の検証ルール変更により `repository_id` だけの条件は作成時に拒否される（sub/job_workflow_ref が必須）[実測]。bootstrap は repo スコープワイルドカード → 実測後の絞り込みが現実的

## 限界と残る疑問

- GitHub-hosted runner の利用料金障害（アカウントの支払い失敗）で private repo の runner が起動せず、repo を public 化して回避。private 前提の企業利用では billing 前提条件として残る [実測]
- `pull_request`（非 target）イベントの `sub` context は未採取。target 設計では不要だが併用時は要確認 [未確認]
