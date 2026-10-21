---
name: worktree
description: git worktree で作業ツリーを分けるときの作成から削除までの手順。並列作業が同じ生成物（api_schemas.ts、alembic の head、package-lock.json）に触るとき、別 PR に分ける変更を同時に進めるとき、捨てるかもしれない大きなリファクタをするとき、共有ツリーにユーザーの未コミット変更があるときに使う。数ファイル規模の変更や、`python3 app.py` の起動が必要な作業では使わない。
---

# worktree での作業

使うかどうかの判断基準は `AGENTS.md` の「エージェントの作業ルール」、運用手順の正本は `docs/knowledge/parallel_work.md` です。最初に読み、この手順と食い違ったら文書に従ってください。

## 作る
1. 担当ファイルが、同時に走っているほかの作業と重ならないことを確認する。重なる場合は worktree を増やさず、片方を待たせる。
2. 1 worktree = 1 ブランチ = 1 PR で作る。

   ```sh
   git fetch origin
   git worktree add -b <branch> ../Chat-Core-<name> origin/main
   ```

3. フロントエンドを動かす場合は、`frontend/node_modules` を共有ツリーのものへシンボリックリンクする。worktree では `npm install`／`npm ci`／`npm update` を実行しない（リンク先の共有ツリーが壊れる）。

## 作業中
- 担当する worktree の外は触らない。ほかの作業への依存が分かったら、その場で止めてユーザーに報告する。
- DB・Redis・ポートは共有される。migration の適用や `docker-compose up` は同時に 1 つだけにする。
- `.env` が無いので、`python3 app.py` の起動が必要な作業は共有ツリーで行う。

## 片付ける
1. コミット、push、PR 作成を済ませる。
2. `git -C <worktree> status --short --untracked-files=all` で、残すべきファイルが無いことを確認する。未保存の成果があれば削除を保留してユーザーに報告する。
3. その worktree を使っている自分の dev サーバー、テストプロセス、サブエージェントを止める。
4. 共有ツリーへ移動してから `git worktree remove <worktree>` を実行する。`--force` や `rm -rf` は使わない。
5. `git worktree list` で消えたことを確認する。PR が参照しているブランチは消さない。
