# EXP-002: 並行・重複・再実行の扱い（head SHA 更新 / 並走 PR / 二重起動）

## 目的

同一 PR の連続 push（head SHA 更新）・複数 PR 並走・同一 PR の二重トリガを安全に扱えるか。古い run の cancel、同一 Job の last-wins 判定、VM 数の上限内収束を見る。

## 予測

- `concurrency: microvm-ci-<pr>` + `cancel-in-progress` で、同一 PR の新 run が旧 run を cancel し、Check は最新 SHA の結果で上書きされる [推論]
- 並走 PR は VM が独立に立つ。アカウント適用クォータ（RunMicrovm 1/s、同時メモリ 8GiB）内では 2-4 並行が上限 [仕様+実測: K-346 EXP-001]

## 手順

1. PR#4 を作成し、`synchronize` を 2 連続 push（head SHA: `95be898`→`619c386`→`6ed0763`）
2. PR#3/PR#5 と並走させた状態を観測
3. `workflow_dispatch` を同一 PR 番号で 2 回連続起動（二重 webhook の模擬）
4. `runMicrovmAttempts` / `list-microvms` で VM の収束を確認

## 結果 [実測]

| ケース | 観測（`evidence/runs.json`） |
|---|---|
| head SHA 更新 | `95be898` → cancelled、`619c386` → cancelled、`6ed0763` → success。Check は最新 SHA のみ緑 |
| 同一 PR 二重 dispatch | `39291975852`（先行）= cancelled、`39291987587`（後行）= success。concurrency group `microvm-ci-4` で直列化+キャンセル |
| 並走 PR（#3/#4/#5） | 各 PR が独立 job_id/VM を持ち干渉なし。`ServiceQuotaExceededException` が出た burst は EXP-004 で分離計測 |
| VM 残存 | 全 run 完了後 `list-microvms` で k344-ci RUNNING=0（EXP-006） |

注意点として `pending` 状態の run が `cancel-in-progress` で即時キャンセルされるのではなく、実行開始時点で旧 run をキャンセルする挙動を観測（run `39292268559` が約3.5分 pending の後に旧 run を cancelled）[実測] — GHA 側の runner 取得遅延が混ざると cancel 反映が遅れる。

## 解釈

- last-wins は GHA concurrency で担保できるが、「cancel された run の VM は SIGTERM → finally → terminate」という in-job 清掃が前提。EXP-004 で実証済み
- job_id = `pr<N>-r<run_id>-a<attempt>`、clientToken = sha256(job_id)[:32] により、boto3 内部リトライの RunMicrovm 再送は冪等 [実装]
- 二重 webhook（GitHub 再送）の直接注入は手段がないが、同一 PR の連続イベント処理は concurrency group で等価に dedup される [推論]

## 限界と残る疑問

- 文字通りの二重 webhook delivery（同一 delivery の replay）は GitHub 側でしか起こせず未検証 [未確認]。concurrency group が同一 run_id ではなく同一 PR で直列化するため副作用は限定される [推論]
- 4+ の同時 PR（8GiB 枠を超えるバースト）での queueing 実装はない。現状は retry→最終的に失敗→Check fail となる設計（EXP-004 参照）[実測]
