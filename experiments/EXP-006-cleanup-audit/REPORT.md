# EXP-006: クリーンアップ監査（VM/S3/role の全経路棚卸し）

## 目的

全実験経路（pass/fail/timeout/cancel/dedup/tamper/throttle）を通して VM と S3 一時資源が全て回収されたかを棚卸しする。

## 予測

- k344-ci 由来の VM は全て TERMINATED。sweeper の aliveVms=0
- S3 には各 run の artifact+result が残り、lifecycle 設定（artifacts 2d/evidence 14d）で自然消滅する

## 手順

1. `aws lambda-microvms list-microvms` で `imageArn==k344-ci` のものを列挙
2. sweeper workflow を dispatch 実行（実環境の動作確認）
3. `aws s3 ls s3://k344-prci-155936382172/ --recursive` で残存を確認

## 結果 [実測]

- `evidence/vm-inventory.txt`: k344-ci の VM 15/15 TERMINATED（runner-cancel で作られた `microvm-4cc6816c`、sha-tamper の `microvm-dc2e0f80`、timeout の `microvm-e3a713e8` 等を含む）
- sweeper run `39292121974`（`microvm-ci-sweeper` workflow, `ref:refs/heads/main` sub で OIDC 認証）: `aliveVms=0`, `s3Deleted=0`
- S3 には `ci/pr-N/<sha>-r<run>/artifact.tar.gz` と `result.bundle.tar.gz` が run ごとに残る設計通り。`compare/source.zip`（CodeBuild 用）と `artifacts/ci-image.zip`（image build 用）も配置済み
- 他実験（k342/k346）の VM が同居する account で sweeper が `image-arn` フィルタを持つことで他実験 VM を殺さないことを確認 [実測]

## 解釈

- 3 層の防衛が機能: (1) `finally`+SIGTERM で VM terminate、(2) `maximumDurationInSeconds=900` の hard cap、(3) sweeper 定期掃討。(1) が全経路で効いたため (3) の出番は今回無し [実測]
- S3 の一時資源は「run ごとの prefix」を作る設計で、証拠の参照可能性と清掃の両立が取れた [実装]

## 限界と残る疑問

- `maximumDurationInSeconds` は上限保証であって「run 側の即時清掃」ではない。runner が kill -9 された場合（network断など）は ~900s の残留を許容する。これを短くしたい場合は `idlePolicy.maxIdleDurationSeconds` 側で絞る [推論]
- S3 lifecycle は「最低保持期間」なので、証拠長持ちが必要なら `evidence/` prefix を別設計に [実装]
- sweeper は image-arn 絞り込みなので、他 image への誤爆はないが、同じ image を共有する他実験（k346 の m512 等）は別 image 名のため影響なし [実測]
