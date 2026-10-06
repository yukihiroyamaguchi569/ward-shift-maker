# Cloudflare 移行案

## 結論

Cloudflareへの移行は、現時点では見送る。現行アプリで使用している `ortools` のCP-SATソルバーは通常のCloudflare Workersでは動作が難しく、移行するには **Cloudflare Containers** が必要となる。

Cloudflare ContainersはWorkers Paidプランとコンテナ利用料が必要であるため、無料運用を前提とする現状では移行コストに見合わない。引き続きRenderで運用する。

## 現行構成

- FastAPI / Uvicorn
- Python 3.11
- `openpyxl` によるExcel入出力
- `ortools` による勤務表の最適化
- Render Web Serviceで公開

本番URL: https://shift-maker-psac.onrender.com

## 移行先の構成

```text
利用者
  ↓
Cloudflare Worker（公開URL・ルーティング）
  ↓
Cloudflare Container（FastAPI / Uvicorn / ortools / openpyxl）
```

- WorkerはHTTPリクエストを受け、コンテナ内のFastAPIへ中継する。
- ContainerはDockerイメージとしてPython実行環境と依存パッケージを保持する。
- Excelファイルはリクエスト中だけ扱う現在の方式を維持する。永続保存が必要になった場合はR2を検討する。

## 採用しない案

### Python Workersのみ

FastAPIはPython Workersで利用できるが、Python WorkersはPyodide上で実行される。対応するのは純Pythonパッケージ、またはPyEmscripten対応パッケージが中心である。

`openpyxl` は検証候補になるが、ネイティブ依存を含む `ortools` のCP-SATソルバーは現行のままでは適合しにくい。さらにUvicornの起動方式もWorkerの `fetch` ハンドラへ変更する必要がある。

## 実施項目

1. `Dockerfile` を追加し、Python 3.11と `requirements.txt` を使ってFastAPIを起動できるようにする。
2. Cloudflare WorkerとContainerバインディングを定義する `wrangler.jsonc` を追加する。
3. WorkerからContainerへのHTTP中継を実装する。
4. ローカルでDockerを使い、Excelのアップロード・生成・ダウンロードを確認する。
5. Cloudflareのステージング環境へデプロイし、`staff-request-JULY.xlsx` で生成できることを確認する。
6. コンテナのメモリ・CPU使用量、起動待ち時間、利用料金を確認する。
7. 問題がなければ独自ドメインまたは `workers.dev` URLを公開し、Renderから切り替える。

## 検証観点

- `ortools` を含むDockerイメージが正常にビルド・起動すること
- Excelのアップロード、勤務表生成、Excelダウンロードが現行と同じように動くこと
- 勤務表の生成がコンテナのCPU・メモリ・リクエスト時間の制限内に収まること
- アイドル後の起動待ち時間が運用上許容できること
- 勤務表データの保存先を追加する場合、保存期間・アクセス制御を決めること

## 注意点

- Cloudflare ContainersはWorkers Paidプランが必要で、コンテナのメモリ・CPU・ディスク使用量に応じて課金される。
- コンテナ移行はRenderより構成が増え、有料プランも必要となるため、現時点ではRenderを継続する。
- 勤務表には職員情報が含まれるため、永続保存やログ出力を追加する場合はデータの扱いを別途設計する。

## 参考資料

- [Cloudflare Containers 概要](https://developers.cloudflare.com/containers/)
- [Cloudflare Containers 料金](https://developers.cloudflare.com/containers/pricing/)
- [Cloudflare Python Workers](https://developers.cloudflare.com/workers/languages/python/)
- [Cloudflare Python Workers のパッケージ制約](https://developers.cloudflare.com/workers/languages/python/packages/)
