# CLAUDE.md

## バージョン

- 画面のバージョンは `static/index.html` のフッター（`病棟勤務表 自動作成システム vX.Y.Z`）の1か所だけにある
- **PR ごとに必ず上げる。** 表記は `MAJOR.MINOR.PATCH`
  - 機能追加（`feat:`）→ MINOR を上げ、PATCH を 0 に戻す（例: 1.1.0 → 1.2.0）
  - 修正・ドキュメント・雑務（`fix:` `docs:` `chore:` `refactor:`）→ PATCH を上げる（例: 1.1.0 → 1.1.1）
  - 互換性のない変更（Excel フォーマットの変更など）→ MAJOR を上げる
- PR 本文の Summary に「バージョン: 1.1.0 → 1.1.1」のように書く
