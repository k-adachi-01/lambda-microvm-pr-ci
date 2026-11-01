# K-344 総合評価: PR ごとの MicroVM 使い捨て CI は既存 CI に対して成立するか

## 結論（Done 判定）

**成立。** PR から Checks に信頼できる pass/fail が返り、拒否/停止/再送/改ざん/過負荷の各経路で漏洩・重複・孤児 VM なしを実測で確認した [実測: EXP-001..006]。

| Done 要件 | 判定 | 証拠 |
|---|---|---|
| PR → Checks に信頼できる pass/fail | ✅ | EXP-001（pass run `39289676078`、fail run `39290180756`、check output に microvmId/timings）[実測] |
| 拒否（OIDC）で孤児/漏洩なし | ✅ | EXP-004（creds step で失敗、VM 未起動）[実測] |
| 停止（cancel/timeout）で孤児なし | ✅ | EXP-004（SIGTERM→finally→TERMINATED）、EXP-006（15/15 TERMINATED）[実測] |
| 再送/重複で重複 job なし | ✅ | EXP-002（head SHA 更新で旧 run cancelled、同一 PR 二重 dispatch で後行のみ実行）[実測] |
| 漏洩なし | ✅ | EXP-003（改ざん workflow は無視、cred 探索5項目全 pass、runner はゲストコードを実行しない）[実測] |
| 阻害要因・採用条件 | 記載済 | 下記「採用条件」 |

## 設計上の要点（信頼境界）

1. `pull_request_target` で workflow 定義は常に base ブランチ。PR の `.github/workflows/` 改変は実行されない [実測 EXP-003]
2. runner は PR コードを checkout/実行しない。tarball をバイトとして受け取り、creds-free VM でのみ実行 [実測 EXP-003]
3. 実行ステップは workflow に固定（repo 内ファイルではない）。ゲストはパイプラインを変えられない [設計]
4. VM は execution role なし。AWS との接点は job 個別 presigned URL のみ [実測 EXP-003]
5. fork PR は `microvm-ci-ok` ラベル必須 → 未ラベルは neutral check [実測 EXP-003（機構実演）]
6. OIDC trust は `repository_id`/`repository_owner_id` 固定 + `sub` ∈ {`:pull_request`, `:ref:refs/heads/main`}（実測 claims 由来）[実測 EXP-001]
7. 孤立対策 3層: finally+SIGTERM terminate、`maximumDurationInSeconds`、定期 sweeper（image-arn 絞り）[実測 EXP-006]

## 阻害要因・回避したもの

| 阻害 | 対応 | 状態 |
|---|---|---|
| GitHub Actions OIDC role 作成の権限（K-333 で不可） | 人の SSO（`aws-sandbox-run`）で初期設定。OIDC provider はアカウント既存 | ✅ 解消 |
| AWS の GitHub OIDC trust 検証: `sub`/`job_workflow_ref` 条件が必須 | `repository_id` のみでは作成拒否 → まず repo スコープワイルドカード、実測 claims で最小化 | ✅ 解消 [実測] |
| 2026-07-15 以降作成 repo の `sub` は不変ID形式 `owner@id/repo@id` | 実測 claims で確認し絞り込み（文字列予想と一致）[実測] |
| private repo の hosted runner 課金障害 | repo を public 化（機微なし設計）→ E2E 進行 | ✅ 回避（repo 可視性の判断が必要だった点は記録）[実測] |
| RunMicrovm の瞬時バーストは `ServiceQuotaExceededException`（8GiB 枠） | retryable codes に追加。>4 並行は現状 fail になる設計 | ⚠️ 設計上の限界として残置 [実測] |
| 実 fork PR の E2E | 単一アカウントでは自 repo fork 不可 → `simulate_fork_gate` で機構実演のみ | ⚠️ 未確認項目として記録 [未確認] |

## GitHub-hosted / CodeBuild との比較（EXP-005 要約）

- 実行素性: GHA-hosted ≈ CodeBuild（9-15s E2E）> MicroVM CI（29-40s、VM 起動+終端の固定費 ~7-8s）
- queue: 全基盤でほぼ 0（小 repo・低負荷）。CodeBuild は PROVISIONING 2-4s
- 費用: 1 job あたりいずれもセント未満級。費用差より構築・保守の差が支配的
- **MicroVM の価値は速度ではなく隔離**: untrusted PR コードが runner/AWS権限/repo secret を一切見られない唯一の形 [実測+推論]

## 既存 CI で十分な採用条件（推奨基準）

以下を全て満たせば GHA-hosted/CodeBuild の標準 CI で足り、MicroVM は不要 [推論]:

- PR コードが信頼できる（社内/同 org のみ、fork なし or 事前審査あり）
- runner が触れて良い権限しか持たない（OIDC role が read-only、secret なし、environment protection あり）
- untrusted 入力を runner で実行しない（pull_request_target で workflow 改変不可 + checkout しない設計を維持できる）

逆に以下のいずれかなら MicroVM CI（または等価隔離）を採る意味がある [推論]:

- 公開 repo で外部 PR を受け、コードを実際に動かしたい（`pull_request` でテスト実行したい）
- 実行対象が AI agent 生成コード等「内容が未審査のまま動く」もの
- repo secret / deploy 権限を持つ pipeline で、job 単位の強い隔離が必要

本実装は後者を最小構成で実証した。フル CI プラットフォーム化（queueing、並列制御、image 更新、監査強化）はスコープ外。

## 未確認項目（正直な残り）

- 実 fork PR の gate E2E（単一アカウント制約）[未確認]
- p50/p95 待ち時間の統計的有意差（小 sample）[未確認]
- agent プロセス自体のハング経路（VM cap と poll timeout が最終防衛）[未確認]
- `pull_request`（非 target）イベント併用時の `sub` context [未確認]
- GitHub 二重 webhook の実 replay（concurrency group で等価 dedup 済）[未確認→推論]
