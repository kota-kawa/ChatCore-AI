# 並行作業（git worktree）の運用手順

サブエージェントと worktree をいつ使うかの判断基準は `../../AGENTS.md` の「エージェントの作業ルール」にあります。ここには、worktree を分けた後に守る運用手順だけを置きます。

## 資源と並行数

- 並行数の上限は worktree の本数ではなく、担当ファイルが重複しないことで決まります。同じファイルを編集する予定の作業は worktree を増やしても解決せず、片方を待たせます。
- 重複が無ければ機械資源は制約になりません。worktree 1 本あたり数百 MB で、`.git` は worktree 間で共有されます。
- 1 worktree = 1 ブランチ = 1 PR です。同時にオープンする PR の本数に上限は設けませんが、1 本マージするたびに残りを `main` へリベースする手間が増えるため、本数を増やす前に重複の無い単位へ切れているかを確認します。

## worktree 間で共有される資源

- DB／Redis／ポートは worktree 間で共有されます。alembic migration の適用や `docker-compose up` を伴う作業は同時に 1 つだけにしてください。
- `.env` は git 管理外のため、新規 worktree では `python3 app.py` を起動できません。起動が必要な作業は共有ツリーで行います。

## 依存のある作業

- 依存のある作業は同時に走らせず、先行側が終わってから始めます。
- 並列作業中に他の作業への依存が判明したら、その場で止めてユーザーに報告します。担当 worktree の外を触って解決しようとしないでください。

## worktree でフロントエンドを検証する

- `frontend/node_modules` を共有ツリーのものへシンボリックリンクします。

  ```sh
  ln -s <共有ツリー>/frontend/node_modules <worktree>/frontend/node_modules
  ```

- これで `npm run typecheck`／`npm run lint`／`npm run test`（`test:logic` と `test:components` を順に実行）が動きます。
- リンク先の共有ツリーを壊すため、worktree では `npm install`／`npm ci`／`npm update` を実行しないでください。
