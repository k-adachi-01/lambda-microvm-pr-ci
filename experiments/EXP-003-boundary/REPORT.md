# EXP-003: 信頼境界 — 改ざん workflow の無効化、ゲスト cred 探索、fork ゲート

## 目的

- PR が `.github/workflows/microvm-ci.yml` を改変しても実行されるのは base ブランチの workflow か
- MicroVM 内で untrusted コードが AWS 権限・control plane に到達できるか
- fork PR の未許可実行を止める機構が機能するか

## 予測

- `pull_request_target` では head の workflow 変更は実行されない（base が走る）[仕様]
- VM は execution role なし・環境変数 AWS_* なし・IMDS/メタデータ到達不可 → cred 探索テストは全パス（=漏洩なしの証明）[推論]
- fork PR は `microvm-ci-ok` ラベルが無いと neutral check で止まる [推論]

## 手順（PR#3: `exp/hostile`）

1. head で `.github/workflows/microvm-ci.yml` を改ざん（`microvm-ci-EVIL` + cred 窃取 step 挿入）
2. `tests/test_no_aws_creds.py` を追加（env/IMDS/メタデータ/`/proc/*/environ` の5検査）
3. run の step 一覧に改ざん step が無いこと、VM 内ログで検査テストの結果を確認
4. fork ゲートは `simulate_fork_gate=true` の dispatch で経路を実演

## 結果 [実測]

| 検査 | 結果 |
|---|---|
| workflow 改ざん | run `39290342885` の step 一覧に `EVIL exfiltrate` step は存在せず。job_workflow_ref=`…/microvm-ci.yml@refs/heads/main`（EXP-001 claims）[実測] |
| ゲスト cred 探索 | VM 内ログ: `test_no_aws_env ok` / `test_no_imds ok` / `test_no_metadata_on_169254170253 ok` / `test_no_process_environ_leak ok` / `test_no_aws_config_files ok`。9 tests OK（`evidence/run-39290342885/…/logs.txt`）[実測] |
| fork ゲート | `simulate_fork_gate` run `39293193999`: neutral check-run（conclusion=neutral, title=`not run — fork requires label`）を GITHUB_TOKEN で POST 成功 → early exit、VM 未起動 [実測] |
| runner 側不実行 | runner は head tarball を `gh api tarball` でバイト取得するのみ（checkout/実行なし）。改ざん workflow・悪意テストは runner では一度も実行されていない [実測/設計] |

## 解釈

- 制御面（runner）とゲスト実行面（VM）の分離が成立。`pull_request_target` の「workflow 定義は base のもの」を武器に、改ざん自体を構造的に無効化 [実測]
- VM が creds-free であることは「テストがパスする」形で内側から証明できる。presigned URL は job 個別・9xx 秒で失効するため、仮に guest が URL を読んでも他人の結果は触れない設計 [実測+設計]
- 未ラベル fork は neutral check で視覚的に「未実行」と分かる（fail 扱いにならない）[実測]

## 限界と残る疑問

- 実 fork PR の E2E は未検証: 単一 GitHub アカウントでは自 repo の fork を作成できず。gate の条件分岐・neutral check POST は `simulate_fork_gate` で実演済みだが、`head.repo.fork==true` の実イベントは未観測 [未確認]。閉じ方: 別アカウント or 組織内の fork を用意して `microvm-ci-ok` ラベル運用を試す
- 改ざん検査は「改ざんが実行されない」ことの証明であって「base workflow が正しい」証明ではない。base への push 権限管理は別レイヤ（branch protection）[推論]
- guest が presigned URL を通して他 job の成果物を改ざんできないかの攻撃実験は未実施（URL は job ごとの key に限定され、`PUT` は `result.bundle` のみ）[推論/設計]
