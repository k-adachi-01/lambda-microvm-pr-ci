# EXP-005: GitHub-hosted runner / CodeBuild / Lambda MicroVM の同一テスト比較

## 目的

同一 repo・同一テスト（`python3 -m compileall src -q` + `python3 -m unittest discover -s tests -v`）を3基盤で走らせ、queue を含む待ち時間・費用・構築保守工数を分離する。

## 予測

- 純粋な実行時間は全基盤で数秒（軽い unittest）。差は起動/プロビジョニング/queue に出る [推論]
- MicroVM は 8GiB クォータで同時並行が ~4 に制限される（K-346 EXP-001 実測）一方、GHA/CodeBuild は遥かに緩い

## 手順

- `gha-baseline.yml`: `pull_request` で runner 直接実行。queue = `created_at`→`run_started_at`
- CodeBuild `k344-prci-compare`: source = repo zip on S3、`buildspec.yml` に同一コマンド。4 本並列 `start-build`
- microvm-ci: 各 run の summary `timings` + run 全体時間

## 結果 [実測]（全て小サンプル n≈10 前後）

| 基盤 | queue（待ち） | 実行/VM部分 | E2E（job 全体） | 備考 |
|---|---|---|---|---|
| GHA-hosted `ubuntu-latest` | <1s（全 sample で created=started、秒粒度）[実測] | unittest 2-3s | 5-15s | billing 障害がなければ queue ほぼゼロ |
| CodeBuild `BUILD_GENERAL1_SMALL` | QUEUED 0s [実測] | PROVISIONING 2-4s + BUILD 2-3s | 9-11.5s | 4 並列でも queue≈0 |
| MicroVM CI | <1s（GHA job 即時起動）+ RunMicrovm 0.2-0.7s | VM launch ~4s + job ~4s + terminate ~3.5s | run 全体 29-40s（job+artifact+check 更新込み） | 8GiB 枠で ~4 並行上限 |

- microVM の「VM を使う部分」は 13.7s/9.9s/21.3s(timeout) — K-333 の 12.9–15.3s と整合 [実測]
- CodeBuild の QUEUED 0s は「暖かい」状態の計測。cold では PROVISIONING がもっと掛かる報告例あり [推論]
- `run_started_at` は秒粒度なので <1s の queue は分解できない [未確認: より細かい粒度]

## 費用（概算・2026-10 時点価格）[仕様]

| 項目 | 単価感 | 本PoCの1 job 当たり |
|---|---|---|
| GHA-hosted Linux 2vCPU | private repo で課金対象（public 無料）。~$0.008/分 | ~15s → 約 $0.002 |
| CodeBuild SMALL | ~$0.005/分（`BUILD_GENERAL1_SMALL`） | ~10s → 約 $0.001 |
| MicroVM | Lambda 料金体系（GB-s）。~4s 起動+~4s 実行 | ~10s の 2GiB 分 + S3/API 微量 |
| 制御面 | GHA runner 分 + OIDC+presign+check 更新 API | 無料枠内 |

※ 精緻な単価確定は別途。比較の本質は「VM を毎回立てる分の固定オーバーヘッド（起動+terminate ~7s）が乗る」点。

## 構築・保守工数 [実測]

- microvm-ci: `ci_job.py` ~380行 + `ci_agent.py` ~310行 + workflow ~200行 + infra policies ~150行。イメージ固定で guest は payload 差し替えのみ
- gha-baseline: workflow ~30行（比較にならない単純さ）
- CodeBuild: project + role + source zip アップロード（deploy-codebuild.sh ~80行）+ buildspec 8行

## 解釈

- 素の速度では GHA-hosted ≈ CodeBuild > MicroVM（起動+終端の固定費 ~7-8s）。MicroVM の価値は速度ではなく**隔離**: untrusted コードが runner/AWS権限/repo secret に触れない唯一の形 [実測+推論]
- 費用は 1 job あたりいずれもセント未満〜数セント級で、構築・保守の差の方が支配的。MicroVM は「専用イメージ+オーケストレータ」の固定コストが高い [推論]

## 限界と残る疑問

- n が小さい。p50/p95 の信頼区間は出せない。より多数の sample（~50）で再測する価値あり [未確認]
- CodeBuild cold provisioning と GHA runner の実 queue（課金復帰後の private repo）を同条件で比較していない [未確認]
- VM 内の test 実行時間自体は基盤差がほぼ無い（同じ python unittest）。差は起動・終端・権限モデル [実測]
